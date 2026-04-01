from urllib.parse import parse_qs, unquote
from flask import Flask, request, jsonify
from flask_cors import CORS
from ytmusicapi import YTMusic
import os
import traceback
import requests
import re
import base64
from flask import Flask, request, jsonify
from pytubefix.cipher import Cipher

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '').strip()
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', '').strip()

def _spotify_basic_auth_header():
    creds = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode('utf-8')
    return {
        'Authorization': 'Basic ' + base64.b64encode(creds).decode('utf-8'),
        'Content-Type': 'application/x-www-form-urlencoded'
    }

@app.route('/spotify/token', methods=['POST'])
def spotify_token_proxy():
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return jsonify({'error': 'Spotify client ID/secret not configured'}), 500

    data = request.get_json() or request.form
    grant_type = data.get('grant_type')

    if grant_type not in ('authorization_code', 'refresh_token'):
        return jsonify({'error': 'Invalid grant_type'}), 400

    payload = {
        'grant_type': grant_type,
        'client_id': SPOTIFY_CLIENT_ID
    }

    if grant_type == 'authorization_code':
        payload['code'] = data.get('code')
        payload['redirect_uri'] = data.get('redirect_uri')
        payload['code_verifier'] = data.get('code_verifier')
    else:
        payload['refresh_token'] = data.get('refresh_token')

    if not payload.get('code' if grant_type == 'authorization_code' else 'refresh_token'):
        return jsonify({'error': 'Required field missing'}), 400

    response = requests.post('https://accounts.spotify.com/api/token', data=payload, headers=_spotify_basic_auth_header())

    try:
        body = response.json()
    except ValueError:
        return jsonify({'error': 'Invalid response from Spotify token endpoint'}), 502

    if not response.ok:
        return jsonify({'error': body.get('error_description') or body.get('error') or 'Token exchange failed', 'detail': body}), response.status_code

    return jsonify(body)

# === AUTO AUTH ===
if os.path.exists('headers_auth.json'):
    yt = YTMusic('headers_auth.json')
    print("✅ Using headers_auth.json (best method)")
elif os.path.exists('oauth.json'):
    yt = YTMusic('oauth.json')
    print("✅ Using oauth.json")
else:
    yt = YTMusic()
    print("⚠️  No auth file — public mode (streams will fail)")

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"items": []})
    try:
        results = yt.search(query, filter="songs")[:8]
        items = []
        for r in results:
            if r.get('videoId'):
                items.append({
                    "title": r.get('title', 'Unknown'),
                    "uploaderName": r.get('artists', [{}])[0].get('name', 'Unknown Artist'),
                    "thumbnail": r.get('thumbnails', [{}])[0].get('url', ''),
                    "videoId": r.get('videoId')
                })
        return jsonify({"items": items})
    except Exception as e:
        print("SEARCH ERROR:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/streams/<videoId>')
def get_stream(videoId):
    try:
        song = yt.get_song(videoId)
        streaming_data = song.get('streamingData', {})
        
        adaptive = streaming_data.get('adaptiveFormats', [])
        all_formats = adaptive + streaming_data.get('formats', [])
        
        audio_formats = [f for f in all_formats if 'audio' in f.get('mimeType', '')]
        
        if not audio_formats:
            raise Exception("No audio formats found in streamingData")
        
        audio_formats.sort(key=lambda x: x.get('bitrate', 0), reverse=True)
        
        print(f"Found {len(audio_formats)} audio formats for {videoId}")
        
        # 1. Prefer any direct 'url' first (highest bitrate possible without decryption)
        for fmt in audio_formats:
            if 'url' in fmt and fmt['url']:
                print(f"Using direct URL (itag: {fmt.get('itag', 'unknown')})")
                return jsonify({"audioUrl": fmt['url']})
        
        # 2. Force fallback to known direct-URL itags (usually no signatureCipher)
        for target_itag in [140, 251, 141, 171]:  # 140=AAC 128kbps, 251=Opus ~160kbps
            for fmt in audio_formats:
                if fmt.get('itag') == target_itag:
                    if 'url' in fmt and fmt['url']:
                        print(f"Using direct fallback URL - itag {target_itag}")
                        return jsonify({"audioUrl": fmt['url']})
                    else:
                        print(f"Itag {target_itag} found but no usable 'url' - keys: {list(fmt.keys())}")
        
        # No direct URL available → try decryption (will fail if pytubefix regex broken)
        print("No direct URL found → attempting signature decryption")
        
        # Fetch current player JS URL dynamically
        player_js_url = None
        print("Extracting player JS URL...")
        
        try:
            music_html = requests.get(
                "https://music.youtube.com",
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            ).text
            match = re.search(r'/s/player/([a-f0-9]{8})/player_ias\.vflset/en_US/base\.js', music_html)
            if match:
                player_id = match.group(1)
                player_js_url = f"https://www.youtube.com/s/player/{player_id}/player_ias.vflset/en_US/base.js"
                print(f"Extracted from music page: {player_js_url}")
        except Exception as e:
            print(f"Music page fetch failed: {e}")
        
        if not player_js_url:
            try:
                watch_url = f"https://www.youtube.com/watch?v={videoId}"
                watch_html = requests.get(watch_url, headers={'User-Agent': 'Mozilla/5.0'}).text
                match = re.search(r'/s/player/([a-f0-9]{8})/player_ias\.vflset/en_US/base\.js', watch_html)
                if match:
                    player_id = match.group(1)
                    player_js_url = f"https://www.youtube.com/s/player/{player_id}/player_ias.vflset/en_US/base.js"
                    print(f"Extracted from watch page: {player_js_url}")
            except Exception as e:
                print(f"Watch page fetch failed: {e}")
        
        if not player_js_url:
            player_js_url = "https://www.youtube.com/s/player/6742b2b9/player_ias.vflset/en_US/base.js"
            print(f"Using hardcoded fallback: {player_js_url}")
        
        print(f"Fetching player JS: {player_js_url}")
        js_response = requests.get(player_js_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if js_response.status_code != 200:
            raise Exception(f"Failed to fetch player JS: {js_response.status_code} - {player_js_url}")
        js = js_response.text
        
        cipher = Cipher(js=js, js_url=player_js_url)
        
        for fmt in audio_formats:
            if 'signatureCipher' in fmt:
                try:
                    cipher_params = parse_qs(fmt['signatureCipher'])
                    base_url = unquote(cipher_params.get('url', [''])[0])
                    sig_ciphered = cipher_params.get('s', [''])[0]
                    sp = cipher_params.get('sp', ['sig'])[0]
                    
                    if base_url and sig_ciphered:
                        sig_decoded = cipher.get_signature(sig_ciphered)
                        audio_url = f"{base_url}&{sp}={sig_decoded}"
                        print(f"Decrypted successfully (itag: {fmt.get('itag')})")
                        return jsonify({"audioUrl": audio_url})
                except Exception as dec_err:
                    print(f"Decryption failed for itag {fmt.get('itag')}: {dec_err}")
                    continue
        
        raise Exception("No playable URL found (decryption failed on all encrypted formats)")
    
    except Exception as e:
        print("=== STREAM ERROR for", videoId, "===")
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 YouTube Music Backend running at http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=True)