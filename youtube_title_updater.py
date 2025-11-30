import os
import json
import base64
import logging
import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
import isodate

# --- Configuration ---
MARKER_TAG = "\n\n[updated-by-bot]" # Yeh description me add hoga taaki dubara update na ho
TARGET_DELAY_MINUTES = 10 # Kitne minutes baad update karna hai
CHECK_WINDOW_MINUTES = 60 # Pichle 1 ghante ki videos hi check karenge (API quota bachane ke liye)

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_credentials_from_env():
    """
    GitHub Secrets se Base64 encoded token read karega.
    Local file system use nahi karenge cloud pe.
    """
    token_b64 = os.environ.get("YOUTUBE_TOKEN_JSON")
    if not token_b64:
        logging.error("YOUTUBE_TOKEN_JSON environment variable not found.")
        return None
    
    try:
        token_json = base64.b64decode(token_b64).decode('utf-8')
        token_dict = json.loads(token_json)
        return Credentials.from_authorized_user_info(token_dict)
    except Exception as e:
        logging.error(f"Token decoding failed: {e}")
        return None

def generate_new_title(old_title):
    """
    Yahan tumhara custom title generator logic aayega.
    Abhi ke liye example return kar raha hu.
    """
    # Example logic: Add prefix or change completly
    return f"🔥 {old_title} - Epic Moments!"

def process_videos():
    creds = get_credentials_from_env()
    if not creds:
        return

    youtube = build('youtube', 'v3', credentials=creds)
    
    try:
        # Step 1: Get recent uploads (Last 50 videos)
        # Hum channel ID hardcode nahi kar rahe, 'mine=True' use kar rahe hain.
        channels_res = youtube.channels().list(mine=True, part="contentDetails").execute()
        uploads_playlist_id = channels_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        playlist_res = youtube.playlistItems().list(
            playlistId=uploads_playlist_id,
            part="contentDetails",
            maxResults=20 # Sirf recent 20 check karo to save quota
        ).execute()
        
        video_ids = [item["contentDetails"]["videoId"] for item in playlist_res.get("items", [])]
        
        if not video_ids:
            logging.info("No videos found.")
            return

        # Step 2: Get Video Details (Snippet needed for Title, Desc, PublishedAt)
        videos_res = youtube.videos().list(
            id=",".join(video_ids),
            part="snippet,status,contentDetails"
        ).execute()

        current_time = datetime.datetime.now(datetime.timezone.utc)

        for video in videos_res.get("items", []):
            vid_id = video['id']
            title = video['snippet']['title']
            description = video['snippet'].get('description', "")
            privacy = video['status']['privacyStatus']
            
            # publishedAt string format: 2023-10-27T10:00:00Z
            published_at_str = video['snippet']['publishedAt']
            published_at = isodate.parse_datetime(published_at_str)

            # Check 1: Must be Public
            if privacy != 'public':
                continue

            # Check 2: Idempotence (Kya yeh pehle update ho chuka hai?)
            if MARKER_TAG.strip() in description:
                logging.info(f"Skipping {vid_id}: Already processed.")
                continue

            # Check 3: Timing Logic
            # Calculate age of video in minutes
            age_delta = current_time - published_at
            age_minutes = age_delta.total_seconds() / 60

            logging.info(f"Checking {vid_id}: Age = {age_minutes:.2f} mins")

            # Condition: Video should be older than 10 mins BUT younger than checking window
            # (Taaki hum saalon purani videos update na karein galti se)
            if age_minutes >= TARGET_DELAY_MINUTES and age_minutes <= CHECK_WINDOW_MINUTES:
                
                new_title = generate_new_title(title)
                
                # Update Logic
                logging.info(f"UPDATING Video: {vid_id} | Old: {title} -> New: {new_title}")
                
                try:
                    # Update Title and Append Marker to Description
                    new_description = description + MARKER_TAG
                    
                    youtube.videos().update(
                        part="snippet",
                        body={
                            "id": vid_id,
                            "snippet": {
                                "title": new_title,
                                "description": new_description,
                                "categoryId": video['snippet']['categoryId'] # Required field
                            }
                        }
                    ).execute()
                    logging.info(f"SUCCESS: Updated {vid_id}")
                    
                except HttpError as e:
                    logging.error(f"API Error updating {vid_id}: {e}")

            elif age_minutes < TARGET_DELAY_MINUTES:
                logging.info(f"Skipping {vid_id}: Too new (wait {TARGET_DELAY_MINUTES - age_minutes:.1f} mins)")
            
            else:
                # Video window se bahar hai (purani video), ignore.
                pass

    except HttpError as e:
        logging.error(f"Global API Error: {e}")

if __name__ == "__main__":
    process_videos()