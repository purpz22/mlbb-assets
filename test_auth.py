from ytmusicapi import YTMusic
import json

try:
    import os
    if os.path.exists('headers_auth.json'):
        yt = YTMusic('headers_auth.json')
        print("[OK] Using headers_auth.json (best method)")
    elif os.path.exists('oauth.json'):
        yt = YTMusic('oauth.json')
        print("[OK] Using oauth.json")
    else:
        yt = YTMusic()
        print("[WARN] No auth file - public mode")
    test = yt.get_song('Krr2u8BUtLw')  # same videoId from your log
    print("get_song keys:", list(test.keys()))
    if 'streamingData' in test:
        print("streamingData found! adaptiveFormats count:", len(test['streamingData'].get('adaptiveFormats', [])))
    else:
        print("No streamingData :(")
except Exception as e:
    print("ERROR:", str(e))