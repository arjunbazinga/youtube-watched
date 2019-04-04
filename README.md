## The goal of the app

is to gather some data about your YouTube watch history and do some light visualization of it. There's a few 
interactive graphs and tables on the Visualize page, and then there's the data itself. An SQLite browser, such as [DB
 Browser for SQLite](https://sqlitebrowser.org/), could be used for viewing and filtering the data like a 
 spreadsheet, as well as making simple graphs.

This is not a tool for exhaustive data gathering/archiving and records keeping. Even if it tried to be, inaccuracies in 
Takeout would not allow for that (read below to see why).
## Data retrieval and insertion process

Takeout's watch-history.html file(s) gets parsed for the available info. Some records will only contain a timestamp of 
when the video was opened, presumably when the video itself is no longer available. Most will also contain the video ID,
 title and the channel title.

All the video IDs are then queried against YouTube Data API for additional information such as likes, tags, number of 
comments, etc. Combined with the timestamps from Takeout, the records are then inserted into a database, located in the 
project directory under the default name of yt.sqlite. Those without any identifying info are collectively inserted as a
 single 'unknown'.

Each successful query to the API uses 11 points, with the standard daily quota being 1M.
The Quotas tab on Google's [Console](https://console.developers.google.com/apis/api/youtube.googleapis.com/overview)
page will show how many have been used up.

Should the process get interrupted for any reason, it's safe to restart it using the same Takeout files; no duplicates 
will be created and no duplicate queries will be made (except 1 every time).

## Takeout quirks and data accuracy

Takeout works strangely (badly). The first three times I've used it, varying numbers of records were returned each time.
The second time returned fewer than the first and the last returned more than the first two, including records older 
than the ones in the first two as well as additional records throughout the whole watch history.
The next few I paid attention to also varied in the amount returned in a similar manner.

The oldest records were from April of 2014, with the Youtube account having been created and first used sometime in 2011.

In addition to that, all the archives were missing some amount of records for each year they did cover, when compared 
to the History page on Youtube, though the difference wasn't drastic. Curiously, the History page was also missing some 
videos that were present in Takeout.

#### Timestamps

In short, the timestamps can be very inaccurate and the app doesn't fix that. They shouldn't be relied on for anything
precise, but would work fine for a rough overview of activity over a given period of time, etc.

There is no timezone information coming from Takeout beyond abbreviations like EDT/PST/CET, some of which may refer to 
multiple different timezones. The timestamps seem to be returned in local time of what's used to browse YouTube 
(or perhaps use Google products in general), including those for videos that were watched in a different timezone.
However, temporarily changing the timezone on my PC, or in Google Calendar, or the region in Google Search Settings
never triggered a change in the timestamps.

One of the worse things happens with DST zones. In the case of zones observing Daylight Saving Time (DST), all of the
timestamps seem to be set to either the DST timezone or the non-DST one, depending on the date the archive was created.
That is, if someone who lives on the East coast of US were to create an archive in May, all the timestamps, including
ones that should be in EST (November - March) would be set to EDT, and vice versa if they were to create it in February.

#### Avoiding duplicate timestamps because of potential different timezones for different Takeout archives

Since different Takeout archives may have different timezones, depending on when/where they were downloaded, there may 
be duplicate timestamps in different timezones. To weed out them out, any timestamps for the same video ID that have
been watched at the same year, month, minute and second as well as less than 26 hours apart are treated as one. This may
 also block a limited amount of legitimate timestamps from being entered. Most if not all of them would be the ones
 attached to the 'unknown' record. Considering the records returned by Takeout are not complete as is, a few
 (7 unknown ones for me) extra lost timestamps seemed like a good trade-off.
