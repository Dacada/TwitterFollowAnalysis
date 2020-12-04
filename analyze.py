#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import random
import json
import dataclasses
import datetime
import pathlib
import sys
import distutils.dir_util
import shutil
import webbrowser
import urllib
import logging
import functools
import textwrap
import matplotlib.pyplot as plt
import tweepy
import jinja2


INFO_TWEET_TEXT_1 = """
Every week I run this algorithm, which takes all the accounts I'm following
and counts how many of their tweets I've interacted with over the last four
weeks. Then I do things with this information, like a shoutout to the best
ones."""

INFO_TWEET_TEXT_2 = """
The source code for this bot is open and can be found here:

https://github.com/Dacada/TwitterFollowAnalysis
"""


def clean_whitespace(s):
    return ' '.join(textwrap.dedent(s).split()).strip()


def format_float(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        n = f(*args, **kwargs)
        return format(n, "0.2f")
    return wrapper


def yesorno(prompt):
    a = input(prompt + ' ').lower()
    return a == 'y' or a == 'yes'


class Config:
    def __init__(self, filename):
        self.filename = filename
        with open(filename) as f:
            config = json.load(f)

        for key in config:
            attrname = key.replace('-', '_')  # not foolproof but it will do
            setattr(self, attrname, config[key])

        self._api = None

    def save(self):
        config = {}
        for attrname in self.__dict__:
            if attrname.startswith('_'):
                continue
            key = attrname.replace('_', '-')  # again, not foolproof
            config[key] = getattr(self, attrname)

        with open(self.filename, 'w') as f:
            json.dump(config, f)

    def api(self):
        if self._api is None:
            auth = tweepy.OAuthHandler(self.api_key, self.api_secret)
            auth.set_access_token(self.access_token, self.access_token_secret)
            self._api = tweepy.API(auth)
        return self._api


@dataclasses.dataclass
class User:
    id: str
    name: str
    at: str
    total_tweets: int
    pfp_url: str

    follows_back: bool
    following: int
    followers: int

    tweets: int

    liked: int
    retweeted: int
    quoted: int
    replied: int

    @format_float
    def ratio(self):
        if self.following == 0:
            return 0
        else:
            return self.followers / self.following

    def url(self):
        return 'https://twitter.com/' + self.at

    def _ratio(self, param):
        if self.tweets == 0:
            return 0
        else:
            return param / self.tweets * 100

    @format_float
    def liked_ratio(self):
        return self._ratio(self.liked)

    @format_float
    def retweeted_ratio(self):
        return self._ratio(self.retweeted)

    @format_float
    def quoted_ratio(self):
        return self._ratio(self.quoted)

    @format_float
    def replied_ratio(self):
        return self._ratio(self.replied)

    def score(self):
        if self.tweets == 0:
            return 0

        score = (self.liked + self.retweeted * 10 +
                 self.quoted * 5 + self.replied * 3) * self.tweets

        if not self.follows_back:
            if self.followers == 0:
                score = 0
            else:
                score /= max(1, self.tweets * (self.following/self.followers))

        return int(score)


def get_script_path():
    return pathlib.Path(sys.argv[0]).resolve().parent


def get_current_week_year():
    now = datetime.datetime.now()
    week = now.isocalendar()[1]
    year = now.year
    return week, year


def iter_week_year_backwards(week, year):
    while True:
        yield week, year

        if week == 1:
            week = 52
            year -= 1
        else:
            week -= 1

        if year < 0:
            break


def create_fren_info(config):
    logging.warning("Creating fren info from Twitter API!")
    api = config.api()
    me = api.me()
    users = {}
    for fren in tweepy.Cursor(
            api.friends,
            wait_on_rate_limit=True,
            count=200,
            skip_status=True,
            include_user_entities=False).items():
        logging.warning(f"Processing fren {fren.name}...")
        frenship = api.show_friendship(source_id=me.id, target_id=fren.id)
        follows_back = frenship[1].following

        one_month_ago = datetime.datetime.now() - datetime.timedelta(days=30)

        tweets = 0
        liked = 0
        retweeted = 0
        for tweet in tweepy.Cursor(
                api.user_timeline,
                fren.id,
                wait_on_rate_limit=True,
                count=200,
                trim_user=True,
                include_rts=True,
                exclude_replies=False).items():
            if tweet.created_at < one_month_ago:
                break

            tweets += 1

            if tweet.retweeted:
                retweeted += 1
            if tweet.favorited:
                liked += 1

        users[fren.id] = User(
            id=fren.id_str,
            name=fren.name,
            at=fren.screen_name,
            total_tweets=fren.statuses_count,
            pfp_url=fren.profile_image_url_https,

            follows_back=follows_back,
            following=fren.friends_count,
            followers=fren.followers_count,

            tweets=tweets,

            liked=liked,
            retweeted=retweeted,
            quoted=0,
            replied=0,
        )

    for tweet in tweepy.Cursor(
            api.user_timeline,
            me.id,
            wait_on_rate_limit=True,
            count=200,
            trim_user=True,
            include_rts=True,
            exclude_replies=False).items():

        if tweet.created_at < one_month_ago:
            break

        if tweet.is_quote_status and hasattr(tweet, 'quoted_status'):
            author = tweet.quoted_status.author.id
            if author in users:
                users[author].quoted += 1

        replied = tweet.in_reply_to_user_id
        if replied is not None and replied in users:
            users[replied].replied += 1

    return list(users.values())


def get_fren_info(config):
    week, year = get_current_week_year()
    return get_fren_info_from(config, week, year, create=True)


def get_fren_info_from(config, week, year, create=False):
    filename = f'frens_{week}_{year}.json'

    scriptpath = get_script_path()
    filepath = scriptpath / 'follow_data' / filename

    if filepath.exists():
        with filepath.open() as f:
            try:
                return load_fren_info(f)
            except TypeError as e:
                msg = e.args[0]
                if '__init__() missing' in msg and \
                   'required positional arguments:' in msg:
                    return None
                raise
    else:
        if not create:
            return None
        frens = create_fren_info(config)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open('w') as f:
            save_fren_info(frens, f)
        return frens


def load_fren_info(f):
    d = json.load(f)
    return [
        User(**fren)
        for fren in d['frens']
    ]


def save_fren_info(frens, f):
    d = {
        'frens': [
            dataclasses.asdict(fren)
            for fren in frens
        ]
    }
    json.dump(d, f)


def show_fren_info(frens):
    htmlpath = get_script_path() / 'html'

    week, year = get_current_week_year()
    htmldir = f'frens_{week}_{year}'
    goalpath = htmlpath / htmldir
    templatepath = htmlpath / 'template'

    shutil.rmtree(goalpath, ignore_errors=True)
    distutils.dir_util.copy_tree(str(templatepath), str(goalpath))

    template = templatepath / 'index.html'
    goal = goalpath / 'index.html'

    with template.open() as f:
        template = jinja2.Template(f.read())
    with goal.open('w') as f:
        f.write(template.render(frens=frens))

    goalurl = urllib.parse.urlparse(
        str(goal), scheme='file', allow_fragments=False)
    webbrowser.open(goalurl.geturl())


def create_info_tweet(api):
    logging.warning("Creating info tweet!")
    s = api.update_status(clean_whitespace(INFO_TWEET_TEXT_1), trim_user=True,
                          wait_on_rate_limit=True)
    api.update_status(clean_whitespace(INFO_TWEET_TEXT_2), trim_user=True,
                      wait_on_rate_limit=True, in_reply_to_status_id=s.id)
    return s.id


def get_or_create_info_tweet(config):
    api = config.api()
    try:
        info_tweet_id = config.info_tweet
        api.get_status(info_tweet_id, trim_user=True, wait_on_rate_limit=True)
    except (KeyError, tweepy.error.TweepError):
        info_tweet_id = create_info_tweet(api)
        config.info_tweet = info_tweet_id
        config.save()

    return info_tweet_id


def tweet_best_frens(config, frens):
    api = config.api()
    info_tweet = get_or_create_info_tweet(config)
    info_tweet_url = f'https://twitter.com/{api.me().id}/status/{info_tweet}'
    nbest = config.shoutouts

    frens.sort(key=lambda fren: fren.score(), reverse=True)
    best_frens = [fren for fren in frens if fren.follows_back][:nbest]

    tweet = f"The best {nbest} accounts I follow.\nGo follow them!\n\n"
    frens_in_tweet = 0
    tweets = []
    enum = enumerate(best_frens)
    while True:
        try:
            i, fren = next(enum)
        except StopIteration:
            break

        if i == 0:
            line = '🥇'
        elif i == 1:
            line = '🥈'
        elif i == 2:
            line = '🥉'
        else:
            line = '🏅'
        line += ' @' + fren.at + '\n'

        tweet += line
        frens_in_tweet += 1

        if frens_in_tweet >= 10:
            tweets.append(tweet)
            tweet = ""
            frens_in_tweet = 0
    if tweet:
        tweets.append(tweet)

    print("Gonna tweet the following:")
    print('='*15)
    for tweet in tweets:
        print(tweet)
        print('-'*15)

    if not yesorno("Tweet this?"):
        print("Not tweeted")
        return

    last_id = None
    for tweet in tweets:
        if last_id is None:
            t = api.update_status(tweet, trim_user=True,
                                  wait_on_rate_limit=True,
                                  attachment_url=info_tweet_url)
        else:
            t = api.update_status(tweet, trim_user=True,
                                  wait_on_rate_limit=True,
                                  in_reply_to_status_id=last_id)
        last_id = t.id


def compute_score_analysis(config, fren):
    week, year = get_current_week_year()
    datapoints = config.unfollow_analysis_datapoints_max
    tags = []
    scores = []

    for week, year in iter_week_year_backwards(week, year):
        info = get_fren_info_from(None, week, year)
        if info is None:
            score = None
        else:
            oldfren = [u for u in info if u.id == fren.id]
            if not oldfren:
                score = None
            else:
                score = oldfren[0].score()

        # we count datapoints even if they're missing
        datapoints -= 1

        if score is not None:
            tags.append(f'{week},{year}')
            scores.append(score)
        if datapoints <= 0:
            break

    scores.reverse()
    tags.reverse()
    return scores, tags


def show_score_analysis(scores, tags):
    print()
    print('\t\t+-----------+---------------+')
    print('\t\t| week,year |         score |')
    print('\t\t+-----------+---------------+')
    for i in range(len(scores)):
        print(f'\t\t| {tags[i]: <9} | {scores[i]: >13} |')
    print('\t\t+-----------+---------------+')
    print()

    plt.plot(tags, scores, 'o-')
    plt.xlabel("week,year")
    plt.ylabel("score")
    plt.xticks(rotation=45)
    plt.subplots_adjust(bottom=0.20)
    plt.show()
    print("\tScore analysis plotted")
    print()


def unfollow_worst_frens(config, frens):
    nworst = config.unfollows
    api = config.api()

    frens.sort(key=lambda fren: (
        fren.score(),
        fren.follows_back,
        fren.total_tweets
    ))

    fren_score_analysis = {}
    worst_frens = []
    for fren in frens:
        if len(worst_frens) >= nworst:
            break
        scores, tags = compute_score_analysis(config, fren)
        if len(scores) >= config.unfollow_datapoints_min:
            fren_score_analysis[fren.id] = (scores, tags)
            worst_frens.append(fren)

    print("The following frens will be unfollowed:")

    for fren in worst_frens:
        print("Will unfollow: @" + fren.at)
        print("Display name: " + fren.name)
        print(fren.url())

        if fren.follows_back:
            print("\t* Follows back.")
        else:
            print("\t* Does not follow back.")
        print(f"\t* Tweets: {fren.tweets}")
        print(f"\t* Likes: {fren.liked} ({fren.liked_ratio()}%)")
        print(f"\t* RTs: {fren.retweeted} ({fren.retweeted_ratio()}%)")
        print(f"\t* QRTs: {fren.quoted} ({fren.quoted_ratio()}%)")
        print(f"\t* Replies: {fren.replied} ({fren.replied_ratio()}%)")
        print(f"\t* Score: {fren.score()}")

        show_score_analysis(*fren_score_analysis[fren.id])
        input("press Enter...")

    i = input('To execute the unfollowing type "Destroy Friendships": ')
    if i == "Destroy Friendships":
        for fren in worst_frens:
            print("Unfollowing fren:", fren.name, f"({fren.at})...")
            api.destroy_friendship(fren.id)
        print("Frens unfollowed :(")
    else:
        print("No frens unfollowed today.")


def main():
    if len(sys.argv) < 2:
        print('call with an option, one of:')
        print('\tshow')
        print('\ttweet')
        print('\tunfollow')
        exit(1)

    config = Config('config.json')
    frens = get_fren_info(config)

    if sys.argv[1] == 'show':
        show_fren_info(frens)
    elif sys.argv[1] == 'tweet':
        tweet_best_frens(config, frens)
    elif sys.argv[1] == 'unfollow':
        unfollow_worst_frens(config, frens)


if __name__ == '__main__':
    main()
