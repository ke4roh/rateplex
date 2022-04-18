# rateplex
Check movies in the live TV schedule and record ones that might be worth watching

## Configuring
An example rules file will demonstrate available features.

Get your plex_token from any web request to your server from a browser.

Set your library names for finding movies in and recording movies from

rules should include a minimum IMDB score, and can include a date range
and list of genres to exclude.

```
{
  "server": {
    "plex_url": "http://plex.local:32400",
    "plex_token": "asflkj;dfkj;alkjfs",
    "movie_library": "DVR-Movies",
    "tv_library": "DVR-TV"
  },
  "imdb": {
    "skip_ranges": [
      [
        "2022-03-03T07:12:00-05",
        "2022-03-03T07:22:00-05"
      ]
    ]
  },
  "rules": [
    {
      "minImdb": 7,
      "before": 2000,
      "after": 1980,
      "notGenre": [
        "horror",
        "western"
      ]
    },
    {
      "minImdb": 8,
      "before": 1981,
      "notGenre": [
        "horror",
        "western"
      ]
    },
    {
      "minImdb": 6,
      "after": 1999,
      "notGenre": [
        "horror",
        "western"
      ]
    }
  ]
}
```

## Running
It's simple.  Get help the first time and put together the command line you like.

`python3 ./rateplex.py --help`

Note that you can have it delete or list bad recordings (or do nothing to them).  This feature helps with bad reception in case some recording was trash.

If you specify the ``--record`` option, it will automatically schedule recordings for you.  Otherwise, it will just list the shows it found.

## Contributing
Pull requests and forks are welcome!
