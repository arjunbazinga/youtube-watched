import json
import logging
import os
import sqlite3
from os.path import join
from threading import Thread
from time import sleep

from logging import handlers
from flask import (Response, Blueprint, request, redirect, make_response,
                   render_template, url_for, flash)

from youtubewatched import write_to_sql
from youtubewatched import youtube
from youtubewatched.config import DB_NAME
from youtubewatched.convert_takeout import get_all_records
from youtubewatched.utils.app import (get_project_dir_path_from_cookie,
                                      flash_err, strong)
from youtubewatched.utils.gen import load_file, logging_config
from youtubewatched.utils.sql import (sqlite_connection, db_has_records,
                                      execute_query)

record_management = Blueprint('records', __name__)

logging_verbosity_cookie = 'logging-verbosity-level'
cutoff_value_cookie = 'cutoff-value'
cutoff_denomination_cookie = 'cutoff-denomination'
takeout_dir_cookie = 'takeout-dir'


logger = logging.getLogger(__name__)


class ProjectControl:
    """
    Used for changing log files when changing projects (directories), enabling
    logging
    """
    
    logger = None
    cur_dir = None
    

class ThreadControl:
    """
    Used as a single point of reference on anything related to processes started
    by the user on index.html for starting/stopping said processes, getting
    status, current point of progress, etc.
    """
    thread = None
    # either of the two functions that run processes started from
    # index.html have checks placed throughout them for the state of this flag
    # and will exit if it's set to True
    exit_thread_flag = False
    live_thread_warning = 'Wait for the current operation to finish'

    active_event_stream = None
    stage = None
    percent = '0.0'

    def is_thread_alive(self):
        return self.thread and self.thread.is_alive()

    def exit_thread_check(self):
        if self.exit_thread_flag:
            DBProcessState.stage = None
            add_sse_event(event='stop')
            logger.warning('Stopped the DB update thread')
            return True


ProjectState = ProjectControl()
DBProcessState = ThreadControl()
progress = []


def add_sse_event(data: str = '', event: str = '', id_: str = ''):
    progress.append(f'data: {data}\n'
                    f'event: {event}\n'
                    f'id: {id_}\n\n')
    if event in ['errors', 'stats', 'stop']:
        DBProcessState.stage = None


@record_management.route('/')
def index():
    project_path = get_project_dir_path_from_cookie()
    if not project_path:
        return redirect(url_for('project.setup_project'))
    elif not os.path.exists(project_path):
        flash(f'{flash_err} could not find directory {strong(project_path)}')
        return redirect(url_for('project.setup_project'))

    if not ProjectState.logger:
        ProjectState.logger = logging_config(join(project_path, 'events.log'))
    # projects (directories) were changed, changing the log file accordingly
    if project_path != ProjectState.cur_dir:
        for i in ProjectState.logger.handlers:
            if isinstance(i, handlers.RotatingFileHandler):
                i.stream.close()  # closing currently open file
                i.stream = open(join(project_path, 'events.log'), 'a')
    ProjectState.cur_dir = project_path

    if DBProcessState.active_event_stream is None:
        DBProcessState.active_event_stream = True
    else:
        # event_stream() will set this back to True after disengaging
        DBProcessState.active_event_stream = False
    # default values for forms, set when the user first submits a form
    logging_verbosity = request.cookies.get(logging_verbosity_cookie)
    takeout_dir = request.cookies.get(takeout_dir_cookie)
    cutoff_time = request.cookies.get(cutoff_value_cookie)
    cutoff_denomination = request.cookies.get(cutoff_denomination_cookie)

    db = db_has_records()
    if not request.cookies.get('description-seen'):
        resp = make_response(render_template('index.html', path=project_path,
                                             description=True, db=db))
        resp.set_cookie('description-seen', 'True', max_age=31_536_000)
        return resp
    return render_template('index.html', path=project_path, db=db,
                           logging_verbosity=logging_verbosity,
                           takeout_dir=takeout_dir,
                           cutoff_time=cutoff_time,
                           cutoff_denomination=cutoff_denomination)


@record_management.route('/process_status')
def process_status():
    if not DBProcessState.stage:
        return json.dumps({'stage': 'Quiet'})
    else:
        return json.dumps({'stage': DBProcessState.stage,
                           'percent': DBProcessState.percent})


@record_management.route('/cancel_db_process', methods=['POST'])
def cancel_db_process():
    DBProcessState.stage = None
    DBProcessState.percent = '0.0'
    if DBProcessState.thread and DBProcessState.thread.is_alive():
        DBProcessState.exit_thread_flag = True
        while True:
            if DBProcessState.is_thread_alive():
                sleep(0.5)
            else:
                DBProcessState.exit_thread_flag = False
                break
    return 'Process stopped'


def event_stream():
    while True:
        if progress:
            yield progress.pop(0)
        else:
            if DBProcessState.active_event_stream:
                sleep(0.05)
            else:
                break

    # allow SSE for potential subsequent DB processes
    DBProcessState.active_event_stream = True
    progress.clear()


@record_management.route('/db_progress_stream')
def db_progress_stream():
    return Response(event_stream(), mimetype="text/event-stream")


@record_management.route('/start_db_process', methods=['POST'])
def start_db_process():
    resp = make_response('')
    if DBProcessState.is_thread_alive():
        return DBProcessState.live_thread_warning

    logging_verbosity = request.form.get('logging-verbosity-level')
    resp.set_cookie(logging_verbosity_cookie, logging_verbosity,
                    max_age=31_536_000)
    logging_verbosity = int(logging_verbosity)

    takeout_path = request.form.get('takeout-dir')

    project_path = get_project_dir_path_from_cookie()
    if takeout_path:
        takeout_dir = os.path.expanduser(takeout_path.strip())
        if os.path.exists(takeout_dir):
            resp.set_cookie(takeout_dir_cookie, takeout_dir, max_age=31_536_000)
        args = (takeout_dir, project_path, logging_verbosity)
        target = populate_db
    else:
        cutoff_time = request.form.get('update-cutoff')
        cutoff_denomination = request.form.get('update-cutoff-denomination')
        resp.set_cookie(cutoff_value_cookie, cutoff_time, max_age=31_536_000)
        resp.set_cookie(cutoff_denomination_cookie, cutoff_denomination,
                        max_age=31_536_000)
        cutoff = int(cutoff_time) * int(cutoff_denomination)

        args = (project_path, cutoff, logging_verbosity)
        target = update_db

    DBProcessState.thread = Thread(target=target, args=args)
    DBProcessState.thread.start()

    return resp


def _show_front_end_data(fe_data: dict, conn):
    """
    Composes a basic summary shown at the end of adding Takeout or updating
    records
    """
    fe_data['records_in_db'] = execute_query(
        conn, 'SELECT count(*) from videos')[0][0]
    fe_data['timestamps'] = execute_query(
        conn, 'SELECT count(*) from videos_timestamps')[0][0]
    at_start = fe_data.get('at_start', None)
    if at_start is not None:
        fe_data['inserted'] = fe_data['records_in_db'] - at_start
    if DBProcessState.stage:
        add_sse_event(event='stop')
    add_sse_event(json.dumps(fe_data), 'stats')


def populate_db(takeout_path: str, project_path: str, logging_verbosity: int):

    if DBProcessState.exit_thread_check():
        return

    progress.clear()

    DBProcessState.percent = '0'
    DBProcessState.stage = 'Processing watch-history.html file(s)...'
    add_sse_event(DBProcessState.stage, 'stage')
    records = {}
    try:
        for f in get_all_records(takeout_path, project_path):
            if DBProcessState.exit_thread_check():
                return
            if isinstance(f, tuple):
                DBProcessState.percent = f'{f[0]} {f[1]}'
                add_sse_event(DBProcessState.percent, 'takeout_progress')
            else:
                try:
                    records = f['videos']
                    if len(records) == 1:  # 1 because of the empty unknown rec
                        add_sse_event('No records found in the provided '
                                      'watch-history.html file(s). '
                                      'Something is very wrong.', 'errors')
                        return
                except KeyError:
                    add_sse_event(f'No watch-history.html files found in '
                                  f'{takeout_path!r}', 'errors')
                    return

                failed_entries = f['failed_entries']
                if failed_entries:
                    add_sse_event(f'Couldn\'t parse {len(failed_entries)} ' 
                                  f'entries; dumped to parse_fails.json '
                                  f'in project directory', 'warnings')
                failed_files = f['failed_files']
                if failed_files:
                    add_sse_event('The following files could not be '
                                  'processed:', 'warnings')
                    for ff in failed_files:
                        add_sse_event(ff, 'warnings')

                total_ts = f['total_timestamps']
                total_v = f['total_videos']
                add_sse_event(f'Videos / timestamps found: '
                              f'{total_v} / {total_ts}', 'info')

    except FileNotFoundError:
        add_sse_event(f'Invalid/non-existent path for watch-history.html files',
                      'errors')
        raise

    if DBProcessState.exit_thread_check():
        return

    db_path = join(project_path, DB_NAME)
    conn = sqlite_connection(db_path, types=True)
    front_end_data = {'updated': 0}
    try:
        api_auth = youtube.get_api_auth(
            load_file(join(project_path, 'api_key')).strip())
        write_to_sql.setup_tables(conn, api_auth)
        records_at_start = execute_query(
            conn, 'SELECT count(*) from videos')[0][0]
        if not records_at_start:
            front_end_data['at_start'] = 0
        else:
            front_end_data['at_start'] = records_at_start

        DBProcessState.percent = '0.0'
        add_sse_event(f'{DBProcessState.percent} 1')
        DBProcessState.stage = ('Inserting video records/timestamps from '
                                'Takeout...')
        add_sse_event(DBProcessState.stage, 'stage')

        for record in write_to_sql.insert_videos(
                conn, records, api_auth, logging_verbosity):

            if DBProcessState.exit_thread_check():
                break

            DBProcessState.percent = str(record[0])
            add_sse_event(f'{DBProcessState.percent} {record[1]}')
            front_end_data['updated'] = record[2]

        _show_front_end_data(front_end_data, conn)
        if DBProcessState.stage:
            add_sse_event(event='stop')
        add_sse_event(json.dumps(front_end_data), 'stats')
        conn.close()
    except youtube.ApiKeyError:
        add_sse_event(f'Missing or invalid API key', 'errors')
        raise
    except youtube.ApiQuotaError:
        add_sse_event(f'API quota/rate limit exceeded, see '
                      f'<a href="https://console.developers.google.com/apis/'
                      f'api/youtube.googleapis.com/overview" target="_blank">'
                      f'here</a>', 'errors')
        raise

    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        add_sse_event(f'Fatal database error - {e!r}', 'errors')
        raise
    except FileNotFoundError:
        add_sse_event(f'Invalid database path', 'errors')
        raise

    conn.close()


def update_db(project_path: str, cutoff: int, logging_verbosity: int):
    import sqlite3

    progress.clear()
    DBProcessState.percent = '0.0'
    DBProcessState.stage = 'Updating...'
    add_sse_event(DBProcessState.stage, 'stage')
    db_path = join(project_path, DB_NAME)
    conn = sqlite_connection(db_path)
    front_end_data = {'updated': 0,
                      'failed_api_requests': 0,
                      'newly_inactive': 0,
                      'records_in_db': execute_query(
                          conn,
                          'SELECT count(*) from videos')[0][0]}
    try:
        api_auth = youtube.get_api_auth(
            load_file(join(project_path, 'api_key')).strip())
        if DBProcessState.exit_thread_check():
            return
        for record in write_to_sql.update_videos(conn, api_auth, cutoff,
                                                 logging_verbosity):
            if DBProcessState.exit_thread_check():
                break
            DBProcessState.percent = str(record[0])
            add_sse_event(f'{DBProcessState.percent} {record[1]}')
            front_end_data['updated'] = record[2]
            front_end_data['newly_inactive'] = record[3]
            front_end_data['newly_active'] = record[4]
            front_end_data['deleted'] = record[5]

        _show_front_end_data(front_end_data, conn)
    except youtube.ApiKeyError:
        add_sse_event(f'{flash_err} Missing or invalid API key', 'errors')
        raise
    except youtube.ApiQuotaError:
        add_sse_event(f'API quota/rate limit exceeded, see '
                      f'<a href="https://console.developers.google.com/apis/'
                      f'api/youtube.googleapis.com/overview" target="_blank">'
                      f'here</a>', 'errors')
        raise
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        add_sse_event(f'{flash_err} Fatal database error - {e!r}', 'errors')
        raise
    except FileNotFoundError:
        add_sse_event(f'{flash_err} Invalid database path', 'errors')
        raise

    conn.close()
