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

## Contributing
Pull requests and forks are welcome!
