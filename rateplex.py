#!/usr/bin/python3

# plexapi would be nice, and could even manage the regular
# library stuff, but we still need the live TV functionality
# to get upcoming recordings, and it's not there yet.
# See https://github.com/nwithan8/python-plexapi

# from plexapi.myplex import MyPlexAccount
# import netrc
# 
# login, acct, password = netrc.netrc().hosts["plex.tv"]
# account = MyPlexAccount(login, password)
# password = None
# plex = account.resource('ke4roh-plex').connect()

from pathlib import Path
import os
import json
import imdb
import argparse
import csv
from imdb._exceptions import IMDbParserError, IMDbDataAccessError
from urllib.error import URLError
from urllib.parse import quote_plus
import requests
import time
import logging
import datetime
import random
from dateutil.parser import isoparse
from ffprobe import FFProbe


class Plex(object):
    def __init__(self, plex_url, plex_token, **kwargs):
        self.plex_url = plex_url
        self.plex_token = plex_token

    def get_libraries(self):
        headers = {'Accept': 'application/json, text/plain, */*'}
        params = (('X-Plex-Token', self.plex_token),)

        return \
            requests.get(self.plex_url + '/library/sections', headers=headers, params=params)\
            .json()["MediaContainer"]["Directory"]

    def get_upcoming_movies(self):
        headers = {'Accept': 'application/json, text/plain, */*'}

        params = (
            ('type', '1'),
            ('includeCollections', '1'),
            ('includeExternalMedia', '1'),
            ('X-Plex-Features', 'external-media,indirect-media'),
            ('X-Plex-Model', 'bundled'),
            ('X-Plex-Container-Start', '0'),
            ('X-Plex-Token', self.plex_token),
            ('X-Plex-Drm', 'widevine'),
            ('X-Plex-Language', 'en')
        )

        return requests.get(self.plex_url + '/tv.plex.providers.epg.cloud:4/sections/1/all', headers=headers,
                            params=params).json()["MediaContainer"]["Metadata"]

    def get_existing_movies(self, index, type):
        if type == "movie":
            type_number = 1
        elif type == "show":
            type_number = 4
        else:
            raise ValueError("type %s" % type)

        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en',
        }

        params = (
            ('type', str(type_number)),
            ('sort', 'duration:desc'),
            ('includeCollections', '1'),
            ('includeExternalMedia', '1'),
            ('includeAdvanced', '1'),
            ('includeMeta', '1'),
            ('X-Plex-Features', 'external-media,indirect-media'),
            ('X-Plex-Model', 'hosted'),
            ('X-Plex-Container-Start', '0'),
            ('X-Plex-Token', self.plex_token),
            ('X-Plex-Text-Format', 'plain'),
            ('X-Plex-Drm', 'widevine'),
            ('X-Plex-Language', 'en'),
        )

        return requests.get(self.plex_url + '/library/sections/%s/all' % index, headers=headers, params=params).json()[
            "MediaContainer"]["Metadata"]

    def record_program(self, movie, library_id):
        params = (
            ('prefs[minVideoQuality]', '0'),
            ('prefs[replaceLowerQuality]', 'false'),
            ('prefs[recordPartials]', 'false'),
            ('prefs[startOffsetMinutes]', '0'),
            ('prefs[endOffsetMinutes]', '0'),
            ('prefs[lineupChannel]', ''),
            ('prefs[startTimeslot]', '-1'),
            ('prefs[comskipEnabled]', '-1'),
            ('prefs[comskipMethod]', '2'),
            ('prefs[oneShot]', 'true'),
            ('prefs[remoteMedia]', 'false'),
            ('targetLibrarySectionID', library_id),
            ('targetSectionLocationID', ''),
            ('includeGrabs', '1'),
            ('hints[guid]', movie["guid"]),
            ('hints[ratingKey]', movie["ratingKey"]),
            ('hints[thumb]', movie["thumb"]),
            ('hints[title]', movie["title"]),
            ('hints[type]', '1'),
            ('hints[year]', movie["year"]),
            # airingChannels is triple URL-encoded,channelIdentifier=channelTitle
            ('params[airingChannels]', quote_plus(
                quote_plus("%s=%s" % (movie["Media"][0]["channelIdentifier"], movie["Media"][0]["channelTitle"])))),
            # airingTimes is double- URL-encoded, comma delimited secs since epoch for start
            ('params[airingTimes]', movie["Media"][0]["beginsAt"]),
            ('params[libraryType]', '1'),
            ('params[mediaProviderID]', '5'),
            ('type', '1'),
            ('X-Plex-Token', self.plex_token),
            ('X-Plex-Language', 'en'),
        )

        return requests.post(self.plex_url + '/media/subscriptions', params=params)

    @staticmethod
    def ffprobe_duration(movie_file):
         lengths = [float(f) for f in filter(lambda n: n.isnumeric(), [s.duration for s in FFProbe(movie_file).streams])]
         return len(lengths) and max(lengths) or None

    @staticmethod
    def check_duration(movie, since=0):
        """
        Check if the (first) file duration is about the same per ffmpeg
        as per plex.  Good recordings tend to be within 1e-6 of the same
        duration, while bad ones tend to be off by a factor >> 1.

        :param movie: a plex record as returned from a query for movies
        :return: true if the file is out of spec
        """
        bad = False
        f = Path(movie["Media"][0]['Part'][0]['file'])
        if f.stat().st_mtime > since:
            probed = Plex.ffprobe_duration(movie["Media"][0]['Part'][0]['file'])
            if probed:
                plexd = movie["Media"][0]['Part'][0]['duration']/1000.0
                difference = (plexd-probed)/probed
                bad = abs(difference) > 0.010
            else:
                bad = False
        return bad

class Range(object):
    def __init__(self, low, high):
        self.low = low
        self.high = high

    def __iter__(self):
        return range(self.low, self.high).__iter__()

    def __contains__(self, item):
        return self.low <= item <= self.high


class IMDb(object):
    """
    An object for managing interaction with IMDb, and particularly
    keeping a long-term cache of titles to tt numbers and
    ratings of movies so that they don't have to be
    repeatedly looked up.

    :argument rules the imdb section of the config file, which might contain a "skip_ranges" array of arrays.
       skip_ranges inner arrays should contain two ISO dates for which to ignore saved ratings.  This is mostly
       userful for debugging.
    """
    __fieldnames = ['guid', 'title', 'year', 'imdbId', 'matchDate', 'rating', 'ratingDate']

    def __init__(self, **rules):
        self.ia = imdb.IMDb()
        self.imdb_ratings = dict()
        self.imdb_lookups = 0
        self.imdb_errors = 0
        self.skip_ranges = []
        if "skip_ranges" in rules:
            self.skip_ranges = [Range(isoparse(x[0]), isoparse(x[1])) for x in rules["skip_ranges"]]

    def __enter__(self):
        self.load_ratings()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.save_ratings()

    @staticmethod
    def pause():
        time.sleep(random.random()+1)

    def load_ratings(self):
        oldest = time.time() - 120 * 24 * 60 * 60
        with open('ratings.csv', newline='') as csvfile:
            self.imdb_ratings = {row['guid']: row for row in csv.DictReader(csvfile)}

    def save_ratings(self):
        logging.info("IMDb lookups: %d, errors: %d" % (self.imdb_lookups, self.imdb_errors))
        oldest = time.time() - 120 * 24 * 60 * 60
        with open('ratings.csv', 'w', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=IMDb.__fieldnames, restval='')
            writer.writeheader()
            now = datetime.datetime.now().isoformat()
            for guid, data in self.imdb_ratings.items():
                rd = isoparse(data.get('ratingDate', now)).timestamp()
                if rd >= oldest and \
                        len(list(filter(lambda x: rd in x, self.skip_ranges))) == 0:
                    writer.writerow(data)

    @staticmethod
    def years_away(movie_a, movie_b):
        return abs(int(movie_a.get("year", 1901)) - int(movie_b.get("year", 1901)))

    def __movie_cache(self, movie):
        if movie['guid'] not in self.imdb_ratings:
            d = dict()
            self.imdb_ratings[movie['guid']] = d
            d['guid'] = movie['guid']
            d['title'] = movie["title"]
            d['year'] = movie.get("year", 1901)
        return self.imdb_ratings[movie['guid']]

    def lookup_movie(self, movie):
        imdb_id = None
        if movie['guid'] in self.imdb_ratings:
            imdb_id = self.imdb_ratings[movie['guid']]['imdbId']
        if not imdb_id:
            # prefer exact match year, but also allow for 1 year off
            imdb_id = sorted(
                [x for x in filter(lambda x: IMDb.years_away(x, movie) <= 1, self.ia.search_movie(movie["title"]))],
                key=lambda x: IMDb.years_away(x, movie)
            )[0].movieID
            movie_cache = self.__movie_cache(movie)
            movie_cache['imdbId'] = imdb_id
            movie_cache['matchDate'] = datetime.datetime.now().isoformat()
            self.pause()
        return imdb_id

    def get_rating(self, movie):
        movie_cache = self.__movie_cache(movie)
        if 'rating' in movie_cache \
                and movie_cache['rating'] and float(movie_cache['rating']) > 0:
            return float(movie_cache['rating'])

        try:
            logging.debug("Performing IMDb lookup for %s (%s)" % (movie["title"], str(movie.get("year", "x"))))
            rating = self.ia.get_movie(self.lookup_movie(movie)).get("rating",None)
            self.pause()
            self.imdb_lookups += 1
        except (RuntimeError, KeyError, IndexError, IMDbParserError, IMDbDataAccessError, URLError):
            logging.warning("IMDb lookup failed for %s (%s)" % (movie["title"], str(movie.get("year", "x"))))
            rating = -1
            self.imdb_errors += 1

        # the call to self.lookup_movie already populated the movie into imdb_ratings
        movie_cache['rating'] = rating
        movie_cache['ratingDate'] = datetime.datetime.now().isoformat()
        return rating and float(rating) or None


class Rules(object):
    """
    A single set of rules to match to record a film
    """

    def __init__(self, rules):
        self.rules = []
        if "notGenre" in rules:
            not_genre = set([x.lower() for x in rules["notGenre"]])
            self.rules.append(lambda m: len(not_genre.intersection(Rules.movie_genre_set(m))) == 0)
        if "before" in rules:
            self.rules.append(lambda m: self.__get_or_call(m, "year", 1901) < rules["before"])
        if "after" in rules:
            self.rules.append(lambda m: self.__get_or_call(m, "year", 1901) > rules["after"])
        if "minImdb" in rules:
            self.rules.append(lambda m: self.__get_or_call(m, "imdbRating", 0) >= rules["minImdb"])

    @staticmethod
    def movie_genre_set(movie):
        return [x['tag'].lower() for x in movie.get("Genre", [])]

    @staticmethod
    def __get_or_call(m, key, default):
        """
        If the value in the map/dict is a callable, replace it with the result of the call
        and return that.

        :param m: a dict
        :param key: a key for a dict
        :param default: the value to return if the key isn't in the dict
        :return: the value at the key if the value is not a callable, the result of
           the callable if it is a callable and the result is not None, 
           the given default otherwise
        """
        x = m.get(key, default)
        if callable(x):
            x = x()
            m[key] = x
            if x is None:
                x = default
        return x

    def test(self, movie):
        for r in self.rules:
            if not r(movie):
                return False
        return True


class RuleSet(object):
    """
    A collection of Rules, any of which might match to
    cause a film to be recorded
    """

    def __init__(self, rules):
        self.rule_sets = [Rules(r) for r in rules]

    def rule_passes(self, movie):
        for r in self.rule_sets:
            if r.test(movie):
                return True
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", type=argparse.FileType('r'))
    parser.add_argument("--output", type=argparse.FileType("w"), default="-")
    parser.add_argument("--record", action='store_true')
    parser.add_argument("--delete-bad", action='store_true')
    parser.add_argument("--list-bad", action='store_true')
    parser.add_argument("--delete-partial", action='store_true')
    parser.add_argument("--log", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO')
    args = parser.parse_args()

    numeric_level = getattr(logging, args.log.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % args.log)
    logging.basicConfig(level=numeric_level)

    config = json.load(args.rules)

    rules = RuleSet(config["rules"])
    plex = Plex(**config["server"])

    video_types = ['movie','show']
    libraries = plex.get_libraries()
    movie_libs = {lib["key"]: plex.get_existing_movies(lib["key"], lib["type"]) for lib in
                  filter(lambda t: t["type"] in video_types, libraries)}
    dvr_movie_lib = [lib["key"] for lib in
                     filter(lambda l: l["type"] == "movie" and l["title"] == config["server"]["movie_library"],
                            libraries)][0]
    dvr_tv_lib = [lib["key"] for lib in
                     filter(lambda l: l["type"] == "show" and l["title"] == config["server"]["tv_library"],
                            libraries)][0]

    # The next bit makes a list of recordings that aren't worth keeping because
    #      1. They have a lot of noise in them making the Plex duration vastly different than the actual duration
    #   or 2. They are partial recordings (presumably cancelled because the signal dropped out)
    #
    # These criteria do not guarantee a flawless recording.  Further analysis with 
    # https://www.avsforum.com/threads/software-to-measure-glitches-from-ota-recordings.2435482/
    # could assess recording quality based on smaller glitches than those two coarse metrics.
    doomed_flix = list()
    if args.delete_bad or args.list_bad:
        since = Path(".scannedBad").stat().st_mtime
        # Identify bad recordings
        bad_recordings = list()
        for lib in [dvr_tv_lib, dvr_movie_lib]:
            bad_recordings.extend(filter(lambda m: plex.check_duration(m,since), movie_libs[lib]))


        logging.info("Bad recordings:")
        logging.info("\n".join(["%s (%s)" % (m["title"], m["year"]) for m in bad_recordings]))
        logging.info("--- end bad recordings")

        if args.delete_bad:
            doomed_flix.extend(bad_recordings)
            Path(".scannedBad").touch()

    # This could be expanded to consider more than part 0
    if args.delete_partial:
        for lib in [dvr_tv_lib, dvr_movie_lib]:
            doomed_flix.extend(
                filter(
                    lambda x: (
                        ("mediaGrabStatus" in x["Media"][0] 
                            and x["Media"][0]["mediaGrabStatus"]=='complete'
                        ) or "mediaGrabStatus" not in x["Media"][0]) 
                        and "mediaGrabPartialRecording" in x["Media"][0], 
                    movie_libs[lib]
                )
            )

    # Actually delete
    for file in filter (lambda x: Path(x).exists(),[movie["Media"][0]['Part'][0]['file'] for movie in doomed_flix]):
        # It might be nice to do this through Plex
        os.remove(file)

    # Immediately take out the bad recordings from the list to skip
    bad_guids = {m["guid"] for m in doomed_flix}
    movie_libs[dvr_movie_lib] = list(filter(lambda m: m["guid"] not in bad_guids, movie_libs[dvr_movie_lib]))

    old_guids = set()
    for movieLib in movie_libs.values():
        old_guids.update([x["guid"] for x in movieLib])

    films = plex.get_upcoming_movies()

    with IMDb(**config.get(imdb, dict())) as im:
        for film in films:
            film["imdbRating"] = lambda x=film: im.get_rating(x)

        films = list(

            filter(
                lambda x:
                "subscriptionID" not in x  # already scheduled to record
                and x["guid"] not in old_guids  # already recorded
                and rules.rule_passes(x),  # good enough
                films
            )
        )

    with args.output as f:
        csvw = csv.writer(f)
        csvw.writerow(["Title", "Year", "IMDB score"])
        films.sort(reverse=True,
                   key=lambda x: (x["imdbRating"], -x["year"]))
        for movie in films:
            if args.record:
                plex.record_program(movie, dvr_movie_lib)
            csvw.writerow([
                movie["title"],
                str(movie["year"]),
                str(movie["imdbRating"])
            ])


if __name__ == "__main__":
    main()
