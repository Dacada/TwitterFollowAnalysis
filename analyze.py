#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
import tweepy
import jinja2


def format_float(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        n = f(*args, **kwargs)
        return format(n, "0.2f")
    return wrapper


def yesorno(prompt):
    a = input(prompt + ' ').lower()
    return a == 'y' or a == 'yes'


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


def get_api(config_file):
    with open(config_file) as f:
        config = json.load(f)

    auth = tweepy.OAuthHandler(
        config['api-key'], config['api-secret'])
    auth.set_access_token(
        config['access-token'], config['access-token-secret'])

    return tweepy.API(auth)


def create_fren_info(api):
    logging.warning("Creating fren info from Twitter API!")
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


def get_fren_info():
    week, year = get_current_week_year()
    filename = f'frens_{week}_{year}.json'

    scriptpath = get_script_path()
    filepath = scriptpath / 'follow_data' / filename

    if filepath.exists():
        with filepath.open() as f:
            return load_fren_info(f)
    else:
        api = get_api('config.json')
        frens = create_fren_info(api)
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


def tweet_best_frens(frens):
    api = get_api('config.json')

    frens.sort(key=lambda fren: fren.score(), reverse=True)
    best_frens = frens[:15]

    tweet1 = "The machine has come to its conclusion. "
    tweet1 += "The top 15 best accounts I follow are:\n\n"
    for i, fren in enumerate(best_frens[:5]):
        at = '@'+fren.at
        if i == 0:
            tweet1 += '🥇'
        elif i == 1:
            tweet1 += '🥈'
        elif i == 2:
            tweet1 += '🥉'
        else:
            tweet1 += '🏅'
        tweet1 += ' ' + at + '\n'

    tweet2 = "The next 10:\n\n"
    for fren in best_frens[5:]:
        at = '@'+fren.at
        tweet2 += '🏅 ' + at + '\n'

    print("Gonna tweet the following:")
    print('='*15)
    print(tweet1)
    print('-'*15)
    print(tweet2)
    print('='*15)

    if not yesorno("Tweet this?"):
        print("Not tweeted")
        return

    t = api.update_status(tweet1, trim_user=True, wait_on_rate_limit=True)
    api.update_status(tweet2, trim_user=True,
                      wait_on_rate_limit=True, in_reply_to_status_id=t.id)


def unfollow_worst_frens(frens):
    api = get_api('config.json')

    frens.sort(key=lambda fren: fren.score())
    worst_score = frens[0].score()
    worst_frens = []
    for fren in frens:
        if fren.score() <= worst_score:
            worst_frens.append(fren)
        else:
            break
    worst_frens.sort(key=lambda fren: fren.tweets)

    unfollowed = 0
    for fren in worst_frens:
        print("About to unfollow @" + fren.at)
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
        print(f"\t* SCORE: {fren.score()}")

        if yesorno("Unfollow?"):
            api.destroy_friendship(fren.id)
            unfollowed += 1
            if unfollowed == 15:
                break
        print()


def main():
    if len(sys.argv) < 2:
        print('call with an option, one of:')
        print('\tshow')
        print('\ttweet')
        print('\tunfollow')

    frens = get_fren_info()

    if sys.argv[1] == 'show':
        show_fren_info(frens)
    elif sys.argv[1] == 'tweet':
        tweet_best_frens(frens)
    elif sys.argv[1] == 'unfollow':
        unfollow_worst_frens(frens)


if __name__ == '__main__':
    main()
