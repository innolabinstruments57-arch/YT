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
# Yeh description mein add hoga taaki script dubara update na kare
MARKER_TAG = "\n\n[updated-by-bot]" 
# Kitne minutes baad video update karna hai (e.g., jab video public ho jaaye)
TARGET_DELAY_MINUTES = 10 
# Sirf pichle 1 ghante ki videos check karenge (API quota bachane ke liye)
CHECK_WINDOW_MINUTES = 60 

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_credentials_from_env():
    """
    GitHub Secrets (YOUTUBE_TOKEN_JSON) se Base64 encoded token read karega.
    """
    token_b64 = os.environ.get("YOUTUBE_TOKEN_JSON")
    if not token_b64:
        logging.error("YOUTUBE_TOKEN_JSON environment variable not found. Please set the GitHub Secret.")
        return None
    
    try:
        # Base64 decode karke JSON string mein convert karna
        token_json = base64.b64decode(token_b64).decode('utf-8')
        token_dict = json.loads(token_json)
        # Credentials object banana
        return Credentials.from_authorized_user_info(token_dict)
    except Exception as e:
        logging.error(f"Token decoding or parsing failed. Regenerate token.json and update the Secret. Error: {e}")
        return None

def get_new_title(old_title):
    """
    GitHub Secret (TODAYS_VIDEO_TITLE) se naya title fetch karega.
    Agar secret nahi mila, toh fallback logic use karega.
    """
    # Naya title ek environment variable (GitHub Secret) se read karo
    new_title_secret = os.environ.get("TODAYS_VIDEO_TITLE")
    
    if new_title_secret:
        # Agar secret set hai, toh uski value return karega
        logging.info(f"Using Title from TODAYS_VIDEO_TITLE Secret.")
        return new_title_secret
    else:
        # Fallback/Default logic (Agar secret set nahi hai)
        logging.warning("TODAYS_VIDEO_TITLE secret not found. Using default logic.")
        return f"🔥 {old_title} | Bot Updated Tagline!"

def process_videos():
    creds = get_credentials_from_env()
    if not creds:
        return

    youtube = build('youtube', 'v3', credentials=creds)
    
    try:
        # Step 1: Get 'Uploads' Playlist ID
        # 'mine=True' se authenticated user ka channel details mil jayenge
        channels_res = youtube.channels().list(mine=True, part="contentDetails").execute()
        if not channels_res.get("items"):
            logging.error("Could not retrieve channel details. Check API permissions.")
            return

        uploads_playlist_id = channels_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        logging.info(f"Uploads Playlist ID: {uploads_playlist_id}")

        # Step 2: Get recent video IDs from the Uploads playlist
        playlist_res = youtube.playlistItems().list(
            playlistId=uploads_playlist_id,
            part="contentDetails",
            maxResults=20 # Sirf recent 20 check karo to save quota
        ).execute()
        
        video_ids = [item["contentDetails"]["videoId"] for item in playlist_res.get("items", [])]
        
        if not video_ids:
            logging.info("No recent videos found in uploads playlist.")
            return

        # Step 3: Get detailed Video Snippet and Status
        videos_res = youtube.videos().list(
            id=",".join(video_ids),
            part="snippet,status"
        ).execute()

        current_time = datetime.datetime.now(datetime.timezone.utc)
        videos_to_update = 0

        for video in videos_res.get("items", []):
            vid_id = video['id']
            title = video['snippet']['title']
            description = video['snippet'].get('description', "")
            privacy = video['status']['privacyStatus']
            
            # PublishedAt ko timezone-aware datetime object mein parse karna
            published_at_str = video['snippet']['publishedAt']
            published_at = isodate.parse_datetime(published_at_str)

            # --- Validation Checks ---
            
            # Check 1: Must be Public
            if privacy != 'public':
                logging.info(f"Skipping {vid_id}: Not public (Privacy: {privacy})")
                continue

            # Check 2: Idempotence (Kya yeh pehle update ho chuka hai?)
            if MARKER_TAG.strip() in description:
                logging.info(f"Skipping {vid_id}: Already processed (Marker found).")
                continue

            # Check 3: Timing Logic
            age_delta = current_time - published_at
            age_minutes = age_delta.total_seconds() / 60

            logging.info(f"Checking {vid_id} ('{title}'): Age = {age_minutes:.1f} mins")

            # Condition: Video should be older than TARGET_DELAY_MINUTES BUT younger than CHECK_WINDOW_MINUTES
            if TARGET_DELAY_MINUTES <= age_minutes <= CHECK_WINDOW_MINUTES:
                
                new_title = get_new_title(title)
                videos_to_update += 1
                
                # --- Update Logic ---
                logging.info(f"ACTION: UPDATING {vid_id} | Old: {title} -> New: {new_title}")
                
                try:
                    # Append Marker to Description (for idempotence)
                    new_description = description.strip() + MARKER_TAG
                    
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
                logging.info(f"Skipping {vid_id}: Too new (wait {TARGET_DELAY_MINUTES - age_minutes:.1f} mins more)")
            
            else:
                logging.info(f"Skipping {vid_id}: Too old (Age: {age_minutes:.1f} mins)")
                
        if videos_to_update == 0:
            logging.info("Run finished. No videos met the update criteria.")

    except HttpError as e:
        logging.error(f"Global API Error (Check Quota/Scope): {e}")

if __name__ == "__main__":
    process_videos()
