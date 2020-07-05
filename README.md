# TwitterFollowAnalysis
A script I made to try to keep only interesting people in my twitter follows.

There must be a config.json file in the same directory with the following
format:

```
{
    "api-key": "whatever",
    "api-secret": "whatever",
    "access-token": "whatever",
    "access-token-secret": "whatever"
}
```

The script will use this to authenticate with Twitter. Then it will go through
each account you're following and through each of their tweets in the last
month. And count how many you liked, retweeted, etc. From this it computes a
score for each account. Which is a formula I made up pretty much on the spot.

Then, to present the data, it renders it into an HTML file and opens it in a
browser. No good reason to do it this way.

It takes a long time to go through all the accounts and tweets so that's saved
and the same data is used until next week. So it's meant to be a weekly thing,
using this script.
