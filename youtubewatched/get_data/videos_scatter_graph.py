import sqlite3

import pandas as pd

y_axis_query_pieces = {
    'Ratio': {'select': '(v.like_count * 1.0 / v.dislike_count) AS Ratio',
              'qualifier': 'AND v.like_count > 0 and v.dislike_count > 0'},
    'TagCount': {'select': 'count(vt.tag_id) as TagCount',
                 'join': 'JOIN videos_tags vt ON v.id = vt.video_id',
                 'groupby': 'GROUP BY v.id'},
    'Duration': {'select': 'v.duration as Duration'},
    'CommentCount': {'select': 'v.comment_count as CommentCount'},
    'TitleLength': {'select': 'length(v.title) as TitleLength'},
}


def make_query(x_axis_type, y_axis_type: str = None):
    if y_axis_type and y_axis_type != 'Views':
        y_select = y_axis_query_pieces[y_axis_type].get('select', '')
        if y_select:
            y_select = ', ' + y_select
        y_join = y_axis_query_pieces[y_axis_type].get('join', '')
        y_qualifier = y_axis_query_pieces[y_axis_type].get('qualifier', '')
        y_group_by = y_axis_query_pieces[y_axis_type].get('groupby', '')
    else:
        y_select, y_join, y_qualifier, y_group_by = '', '', '', ''
    
    x_axis_queries = {
        'LikeRatioDesc': f'''
            SELECT
            v.id as VideoID, 
            (v.like_count * 1.0 / v.dislike_count) AS LikeRatioDesc,
            v.view_count as Views,
            c.title as Channel
            {y_select}

            FROM videos v
            JOIN channels c on v.channel_id = c.id
            {y_join}
            WHERE NOT v.title = 'unknown'
            AND v.dislike_count > 0
            AND v.like_count > 0
            AND Views >= ? AND Views <= ?
            {y_qualifier}
            
            {y_group_by}
            ORDER BY LikeRatioDesc DESC
            LIMIT ?;''',

        'LikeRatioAsc': f'''
            SELECT
            v.id as VideoID,
            (v.like_count * 1.0 / v.dislike_count) AS LikeRatioAsc,
            v.view_count as Views,
            c.title as Channel
            {y_select}

            from videos v
            JOIN channels c on v.channel_id = c.id
            {y_join}
            WHERE NOT v.title = 'unknown'
            AND v.dislike_count > 0
            AND v.like_count > 0
            AND Views >= ? AND Views <= ?
            {y_qualifier}
            
            {y_group_by}
            ORDER BY LikeRatioAsc ASC
            LIMIT ?;''',

        'Views': f'''
            SELECT
            v.id as VideoID, 
            v.view_count as Views,
            c.title as Channel
            {y_select}

            from videos v
            JOIN channels c on v.channel_id = c.id
            {y_join}
            WHERE NOT v.title = 'unknown'
            AND Views >= ? AND Views <= ?
            {y_qualifier}
            
            {y_group_by}
            ORDER BY Views DESC
            LIMIT ?;''',

        'TagCount': f'''
            SELECT
            v.id as VideoID, 
            count(vt.tag_id) AS TagCount,
            v.view_count as Views,
            c.title as Channel
            {y_select}
            FROM
            videos v JOIN channels c on v.channel_id = c.id
            JOIN videos_tags vt on v.id = vt.video_id
            {y_join}

            WHERE NOT v.title = 'unknown'
            AND Views >= ? AND Views <= ?
            {y_qualifier}
            
            {y_group_by}
            GROUP BY VideoID
            ORDER BY TagCount DESC
            LIMIT ?;''',

        'Duration': f'''
            SELECT
            v.id as VideoID,
            v.duration as Duration,
            v.view_count as Views,
            c.title as Channel
            {y_select}
            FROM
            videos v
            JOIN channels c on v.channel_id = c.id
            {y_join}

            WHERE NOT v.title = 'unknown'
            AND v.stream IS NULL
            AND Views >= ? AND Views <= ?
            {y_qualifier}

            {y_group_by}
            ORDER BY Duration DESC
            LIMIT ?;''',

        'CommentCount': f'''
            SELECT
            v.id as VideoID,
            v.comment_count as CommentCount,
            v.view_count as Views,
            c.title as Channel
            {y_select}
            FROM
            videos v
            JOIN channels c on v.channel_id = c.id
            {y_join}

            WHERE NOT v.title = 'unknown'
            AND Views >= ? AND Views <= ?
            {y_qualifier}
            
            {y_group_by}
            ORDER BY CommentCount DESC
            LIMIT ?;''',
    }
    return x_axis_queries[x_axis_type]


def get_data(conn: sqlite3.Connection,
             x_axis_type: str, y_axis_type: str = None,
             min_views: int = 1, max_views: int = 100_000_000_000,
             number_of_records: int = 100):
    """
    Retrieve top 100 video records in accordance with x and y axes selected by
    the user
    """
    if (x_axis_type == y_axis_type or
            (y_axis_type == 'Ratio' and 'Ratio' in x_axis_type)):
        query = make_query(x_axis_type)
    else:
        query = make_query(x_axis_type, y_axis_type)

    df = pd.read_sql(query, conn, params=(min_views, max_views,
                                          number_of_records))
    for col_name in df.columns.values:
        if col_name in ['LikeRatioAsc', 'LikeRatioDesc']:
            df.rename(columns={col_name: 'Ratio'}, inplace=True)
            df['Ratio'] = df['Ratio'].round(2)
            break

    return df
