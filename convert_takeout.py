import itertools
import os
import re
from copy import deepcopy
from datetime import datetime
from typing import Union

from bs4 import BeautifulSoup as BSoup

from utils.gen import (timestamp_is_unique_in_list,
                       remove_timestamps_from_one_list_from_another)

"""
In addition to seemingly only returning an oddly even number of records 
(20300 the first time, 18300 the second), Takeout also seems to only return 
from no farther back than 2014.
When compared to the list you'd get from scraping your YouTube history web page 
directly (which seems to go back to the very start of your account), 
it's missing a number of videos from every year, even the current. The 
current year is only missing 15, but the number increases the further back you 
go, ending up in hundreds.
Inversely, Takeout has 1352 records which are not present on Youtube's 
history page. Only 9 of them were videos that were still up when last checked, 
however. Most or all of them have their urls listed as their titles in Takeout.

There's also 3 videos which have titles, but not channel info. They're no 
longer up on YouTube.

-----

Turns out the reason for BS not seeing all/any divs was an extra,
out-of-place tag - <div class="mdl-grid"> (right after <body>) instead of 
indentation and newlines. Thought BeautifulSoup was supposed to handle that 
just fine, but maybe not or not in all cases. 

Update:
Perhaps the above tag is not out of place, but is paired with a </div> at the 
every end of the file. Its presence still doesn't make sense 
as divs with the same class also wrap every video entry individually.
"""

watch_url_re = re.compile(r'watch\?v=')
channel_url_re = re.compile(r'youtube\.com/channel')


def extract_video_id_from_url(url):
    video_id = url[url.find('=') + 1:]
    id_end = video_id.find('&t=')
    if id_end > 0:
        video_id = video_id[:id_end]

    return video_id


def get_watch_history_files(takeout_path: str = '.') -> Union[list, None]:
    """
    Only locates watch-history.html files if any of the following is
    in the provided directory:
     - watch-history file(s) (numbers may be appended at the end)
     - Directory of the download archive, extracted with the same
    name as the archive e.g. "takeout-20181120T163352Z-001"

    The search will become confined to one of these types after the first
    match, e.g. if a watch-history file is found in the very directory that was
    passed, it'll continue looking for those within the same directory, but not
    in Takeout directories. If you have or plan to have multiple watch-history
    files, the best thing to do is manually move them into one directory while
    adding a number to the end of each name, e.g. watch-history_001.html,
    from oldest to newest.

    :param takeout_path:
    :return:
    """

    dir_contents = os.listdir(takeout_path)
    watch_histories = []
    for path in dir_contents:
        if path.startswith('takeout-2') and path[-5:-3] == 'Z-':
            full_path = os.path.join(takeout_path, path, 'Takeout', 'YouTube',
                                     'history', 'watch-history.html')
            if os.path.exists(full_path):
                watch_histories.append(os.path.join(takeout_path, full_path))
            else:
                print(f'Expected watch-history.html in {path}, found none')
    return watch_histories


def _from_divs_to_dict(path: str, occ_dict: dict = None,
                       write_changes=False) -> dict:
    """
    Retrieves all the available info from the passed watch-history.html file;
    returns them in a dict

    If multiple watch-history.html files are present, get_all_records should be
    used instead.

    :param path:
    :param occ_dict:
    :param write_changes: cuts out unnecessary HTML, reducing the size of the
    file and making its processing faster, if used again. When used through
    get_all_records, will also remove all the duplicate entries found in
    previously processed watch-history.html files (provided the files are in
    chronological order), for faster processing still. Performance improvement
    is negligible, if there's only a few files.
    :return:
    """

    with open(path, 'r') as takeout_file:
        content = takeout_file.read()
        original_content = content
    done_ = '<span id="Done">'
    if not content.startswith(done_):  # cleans out all the junk for faster
        # BSoup processing, in addition to fixing an out-of-place-tag which
        # stops BSoup from working completely
        content = content[content.find('<body>')+6:content.find('</body>')-6]
        fluff = [  # the order should not be changed
            ('<div class="mdl-grid">', ''),
            ('<div class="outer-cell mdl-cell mdl-cell--12-col '
             'mdl-shadow--2dp">', ''),
            ('<div class="header-cell mdl-cell mdl-cell--12-col">'
             '<p class="mdl-typography--title">YouTube<br></p></div>', ''),
            ('"content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1"',
             '"awesome_class"'),
            (('<div class="content-cell mdl-cell mdl-cell--6-col '
              'mdl-typography--body-1 mdl-typography--text-right"></div><div '
              'class="content-cell mdl-cell mdl' '-cell--12-col mdl-typography'
              '--caption"><b>Products:</b><br>&emsp;YouTube'
              '<br></div></div></div>'), ''),
            ('<br>', ''),
            ('<', '\n<'),
            ('>', '>\n')
        ]

        for piece in fluff:
            content = content.replace(piece[0], piece[1])
        content = done_ + '\n' + content
    if occ_dict is None:
        occ_dict = {}
    if content != original_content and write_changes:
        with open(path, 'w') as new_file:
            new_file.write(content)
        print('Rewrote', path, '(trimmed junk HTML).')
    soup = BSoup(content, 'lxml')
    if occ_dict is None:
        occ_dict = {}
    occ_dict.setdefault('videos', {})
    occ_dict['videos'].setdefault('unknown', {'timestamps': []})
    divs = soup.find_all('div', class_='awesome_class')
    if len(divs) == 0:
        raise ValueError(f'Could not find any records in {path} while '
                         f'processing Takeout data.\n'
                         f'The file is either corrupt or its contents have'
                         f' been changed.')
    removed_string = 'Watched a video that has been removed'
    removed_string_len = len(removed_string)
    story_string = 'Watched story'
    for div in divs:
        default_values = {'timestamps': []}
        video_id = 'unknown'
        all_text = div.get_text().strip()
        if all_text.startswith(removed_string):  # only timestamp present
            watched_at = all_text[removed_string_len:]
        elif all_text.startswith(story_string):
            watched_at = all_text.splitlines()[-1].strip()
            if '/watch?v=' in watched_at:
                watched_at = watched_at[57:]
        else:
            url = div.find(href=watch_url_re)
            video_id = extract_video_id_from_url(url['href'])
            video_title = url.get_text(strip=True)
            if url['href'] != video_title:  # some videos have the url as the
                # title. They're usually not available through YT or its API
                default_values['title'] = video_title
                try:
                    channel = div.find(href=channel_url_re)
                    channel_url = channel['href']
                    channel_id = channel_url[channel_url.rfind('/') + 1:]
                    channel_title = channel.get_text(strip=True)
                    default_values['channel_id'] = channel_id
                    default_values['channel_title'] = channel_title
                except TypeError:
                    pass
            watched_at = all_text.splitlines()[-1].strip()

        watched_at = datetime.strptime(watched_at[:-4],
                                       '%b %d, %Y, %I:%M:%S %p')

        occ_dict['videos'].setdefault(video_id, default_values)
        default_keys = list(default_values.keys())
        default_keys.remove('timestamps')
        for key in default_keys:
            # tries to check if the newer record has some data that the one
            # that's already set doesn't. Sets it if so
            if not occ_dict['videos'][video_id].get(key, None):
                occ_dict['videos'][video_id][key] = default_values[key]

        cur_timestamps = occ_dict['videos'][video_id]['timestamps']
        timestamp_is_unique_in_list(watched_at, cur_timestamps, insert=True)

    return occ_dict


def get_all_records(takeout_path: str = '.',
                    dump_json_to: str = None, prune_html=False,
                    verbose=True) -> Union[dict, bool]:
    """
    Accumulates records from all found watch-history.html files and returns
    them in a dict.

    :param takeout_path: directory with watch-history.html file(s) or with
    Takeout directories
    :param dump_json_to: saves the dict with accumulated records to a json file
    :param prune_html: prunes unnecessary HTML and records found in a
    previously processed file, as long as they're passed in chronological order
    :param verbose: Controls verbosity
    :return:
    """
    watch_files = get_watch_history_files(takeout_path)
    if not watch_files:
        print('Found no watch-history files.')
        return False

    occ_dict = {}
    for takeout_file in watch_files:
        print(takeout_file)
        _from_divs_to_dict(takeout_file, occ_dict=occ_dict,
                           write_changes=prune_html)

    all_known_timestamps_ids = list(occ_dict['videos'].keys())
    all_known_timestamps_ids.remove('unknown')
    all_known_timestamps_lists = [i for i in
                                  [occ_dict['videos'][v_id]['timestamps']
                                   for v_id in all_known_timestamps_ids]]
    all_known_timestamps = list(itertools.chain.from_iterable(
        all_known_timestamps_lists))
    unk_timestamps = occ_dict['videos']['unknown']['timestamps']
    unk_timestamps = sorted(
        list(set(unk_timestamps).difference(all_known_timestamps)))
    occ_dict['videos']['unknown']['timestamps'] = unk_timestamps
    remove_timestamps_from_one_list_from_another(all_known_timestamps,
                                                 unk_timestamps)

    if verbose:
        print('Total videos watched/opened:',
              len(all_known_timestamps) + len(unk_timestamps))
        print('Total unknown videos:', len(unk_timestamps))
        print('Unique videos with ids:', len(occ_dict['videos']) - 1)
        # ^ minus one for 'unknown' key
    if dump_json_to:
        import json
        str_timestamps_dict = deepcopy(occ_dict['videos'])
        with open(dump_json_to, 'w') as all_records_file:
            for record in str_timestamps_dict.values():
                for i in range(len(record['timestamps'])):
                    record['timestamps'][i] = str(record['timestamps'][i])
            json.dump(str_timestamps_dict, all_records_file, indent=4)

    return occ_dict['videos']
