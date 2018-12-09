import os
import json
import sqlite3
import time
from ktools import fs
from config import DB_PATH, WORK_DIR, video_tags
from ktools.dict_exploration import get_final_key_paths

logger = fs.logger_obj(os.path.join(WORK_DIR, 'logs', 'fail.log'))


def construct_videos_entry_from_json_obj(json_obj: dict):
    # todo finish this, commit and document everything
    entry_dict = {}
    found_keys_and_paths = []
    for path in get_final_key_paths(json_obj, '',
                                    True, black_list=['localized']):
        last_bracket = path[0].rfind('[\'')
        key = path[0][last_bracket+2:path[0].rfind('\'')]
        # print(key)
        if key in video_tags:
            found_keys_and_paths.append([path[0], key, path[1]])

    for entry in found_keys_and_paths:
        print(entry[0], entry[1], entry[2])
    print(len(found_keys_and_paths))


def populate_video_ids_in_sqlite():
    conn = sqlite3.connect(DB_PATH)

    # watch_url = 'https://www.youtube.com/watch?v='

    with open('video_ids.txt', 'r', newline='\r\n') as file:
        file = file.readlines()
    count = 0
    for line in file:
        count += 1
        stripped_line = line.strip()
        equal_index = stripped_line.find('=')
        video_id = stripped_line[equal_index+1:]
        duration_index = video_id.find('&t=')
        if duration_index > 1:
            video_id = video_id[:duration_index]
        cur = conn.cursor()
        cur.execute("""INSERT INTO youtube_video_ids values (?)""", (video_id,))
        conn.commit()
        cur.close()
    conn.close()
    print(count)


def populate_videos_info_into_sql():
    """Sends API requests for all the videos found via JS scrolling;
    inserts them into the DB"""
    from main import get_api_auth, get_video_info
    api_auth = get_api_auth()
    conn = sqlite3.connect(DB_PATH)
    # conn.row_factory = sqlite3.Row

    # watch_url = 'https://www.youtube.com/watch?v='
    count = 0
    logger.info('-'*10 + 'Starting video info retrieval' + '-'*10)
    cur = conn.cursor()
    cur.execute("""SELECT * FROM youtube_video_ids""")
    ids = cur.fetchall()
    cur.close()
    for row in ids:
        video_id = row[0]
        print(video_id)
        result = get_video_info(video_id, api_auth)
        if result:
            cur = conn.cursor()
            json_string = json.dumps(result)
            cur.execute("""INSERT INTO youtube_videos_info values (?, ?)""",
                        (video_id, json_string))
            conn.commit()
            cur.close()
        else:
            count += 1
        time.sleep(0.01)

    conn.close()
    logger.info('-'*10 + 'Video info retrieval finished' + '-'*10)
    logger.info(f'Total fails: {count}')


def add_datetimes_where_possible():
    import data_prep
    takeout = data_prep.get_data_and_basic_stats_from_takeout(silent=True)
    takeout_found = []
    js = [list(row) for row in data_prep.get_videos_info_from_db()]
    for row in range(len(js)):
        js[row][1] = json.loads(js[row][1])['items'][0]['snippet']['title']
    count = 0
    matches = 0
    for takeout_row in range(len(takeout)):
        if len(takeout[takeout_row]) > 1:
            count += 1
            strip = takeout[takeout_row][0].strip()
            if 'https://www.youtube.com/watch?v=' in strip:
                equal_index = strip.find('=')
                video_id = strip[equal_index+1:]
                duration_index = video_id.find('&t=')
                if duration_index > 0:
                    video_id = video_id[:duration_index]
                compare_to = 'id'
            else:
                video_id = strip
                compare_to = 'title'
            for row in range(len(js)):
                if compare_to == 'id':
                    comparison = (js[row][0], video_id)
                else:
                    comparison = (js[row][1], video_id)
                do_compare = comparison[0] == comparison[1]
                if do_compare:

                    matches += 1
                    del js[row]
                    takeout_found.append(takeout[takeout_row])

                    break

    takeout_found = [row[0] for row in takeout_found]
    takeout_orphans = [row for row in takeout
                       if len(row) > 2 and row[0] not in takeout_found]
    print('Unmatched from takeout:', len(takeout_orphans))
    print('Unmatched from js:', len(js))
    print('Total matches:', matches)


def populate_categories_into_sql():
    def bool_adapt(bool_value: bool): return str(bool_value)

    def bool_retrieve(bool_str): return eval(bool_str)

    sqlite3.register_adapter(bool, bool_adapt)
    sqlite3.register_converter('bool', bool_retrieve)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    with open(os.path.join(WORK_DIR, 'categories.json'), 'r') as file:
        cat_json = json.load(file)
    for category_dict in cat_json['items']:
        etag = category_dict['etag']
        id_ = category_dict['id']
        channel_id = category_dict['snippet']['channelId']
        title = category_dict['snippet']['title']
        assignable = category_dict['snippet']['assignable']

        cur = conn.cursor()
        cur.execute("""insert into categories 
        (id, channel_id, title, assignable, etag) 
        values (?, ?, ?, ?, ?)""", (id_, channel_id, title, assignable, etag))
        conn.commit()
        cur.close()

    conn.close()


def populate_parent_topics_into_sql():
    """Hard-coded table name/structure"""
    from topics import topics_by_category

    conn = sqlite3.connect(DB_PATH)

    for topic_dict in topics_by_category.values():
        for k, v in topic_dict.items():
            parent_topic_str = ' (parent topic)'
            if parent_topic_str in v:
                v = v.replace(parent_topic_str, '')
                print(k + ':', v)
                cur = conn.cursor()
                cur.execute('INSERT INTO parent_topics VALUES (?, ?)',
                            (k, v))
                conn.commit()
                cur.close()
            break
    conn.close()


def populate_sub_topics_into_sql():
    """Hard-coded table name/structure"""
    from topics import topics_by_category

    conn = sqlite3.connect(DB_PATH)

    for topic_dict in topics_by_category.values():
        parent_topic_str = ' (parent topic)'
        parent_topic_name = None
        for k, v in topic_dict.items():
            if parent_topic_str in v:
                parent_topic_name = k
                continue
            insert_tuple = (k, v, parent_topic_name)
            print(insert_tuple)
            cur = conn.cursor()
            cur.execute('INSERT INTO sub_topics VALUES (?, ?, ?)',
                        insert_tuple)
            conn.commit()
            cur.close()
    conn.close()


def populate_tags_into_sql():
    pass


def populate_videos_info_into_proper_table():
    pass


def time_test():
    conn = sqlite3.connect(':memory:',
                           detect_types=sqlite3.PARSE_DECLTYPES)
    cur = conn.cursor()
    from datetime import datetime
    cur.execute('create table b (a timestamp)')
    cur.execute('insert into b values (?)', (datetime.now(),))
    cur.execute('select a from b')
    conn.commit()
    print(cur.fetchone()[0])


if __name__ == '__main__':
    from os.path import join
    with open(join(WORK_DIR, 'video_info.json'), 'r') as file:
        file = json.load(file)

    construct_videos_entry_from_json_obj(file)
