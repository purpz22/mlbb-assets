from ytmusicapi import YTMusic
import json

try:
    yt = YTMusic('headers_auth.json')  # or 'oauth.json' if you have that
    print("Auth loaded successfully!")
    test = yt.get_song('Krr2u8BUtLw')  # same videoId from your log
    print("get_song keys:", list(test.keys()))
    if 'streamingData' in test:
        print("streamingData found! adaptiveFormats count:", len(test['streamingData'].get('adaptiveFormats', [])))
    else:
        print("No streamingData :(")
except Exception as e:
    print("ERROR:", str(e))