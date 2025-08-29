from datetime import datetime, timezone
import requests
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# --- Configuration ---
BSKY_HOST = "https://bsky.social"
MAX_COMMENTS_PER_POST = 75
MAX_WORKERS = 5

def clean_input(input_string):
    """A robust function to remove all non-printable characters from a string."""
    return ''.join(filter(str.isprintable, input_string))

class BlueskySession:
    """Manages a session with the Bluesky API, including automatic token refresh."""
    def __init__(self, handle, password):
        self._handle = handle
        self._password = password
        self.access_jwt = None
        self.refresh_jwt = None
        self.did = None
        self.session_active = False

    def create_session(self):
        """Creates an initial session with the Bluesky server."""
        print("Attempting to create a session...")
        try:
            response = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.createSession",
                json={"identifier": self._handle, "password": self._password},
            )
            response.raise_for_status()
            data = response.json()
            self.access_jwt = data['accessJwt']
            self.refresh_jwt = data['refreshJwt']
            self.did = data['did']
            self.session_active = True
            print(f"✅ Session created successfully for handle: {data['handle']}")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"❌ Failed to create session. Status Code: {e.response.status_code}")
            print(f"   Error: {e.response.json().get('message', 'No error message provided.')}")
            return False

    def _refresh_session(self):
        # (This function remains the same)
        print("\n⚠️ Access token expired. Refreshing session...")
        if not self.refresh_jwt:
            print("❌ No refresh token available.")
            self.session_active = False
            return False
        try:
            response = requests.post(
                f"{BSKY_HOST}/xrpc/com.atproto.server.refreshSession",
                headers={"Authorization": f"Bearer {self.refresh_jwt}"},
            )
            response.raise_for_status()
            data = response.json()
            self.access_jwt = data['accessJwt']
            self.refresh_jwt = data['refreshJwt']
            print("✅ Session refreshed successfully.")
            return True
        except requests.exceptions.HTTPError as e:
            print(f"❌ Failed to refresh session. Status Code: {e.response.status_code}")
            self.session_active = False
            return False

    def _make_request(self, method, xrpc_endpoint, params=None, json_data=None, headers=None, is_retry=False):
        # (This function remains the same)
        if not self.session_active: raise Exception("Session is not active.")
        if headers is None: headers = {}
        headers["Authorization"] = f"Bearer {self.access_jwt}"
        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        try:
            response = requests.request(method, full_url, params=params, json=json_data, headers=headers)
            response.raise_for_status()
            return response.json() if response.content else None
        except requests.exceptions.HTTPError as e:
            error_data = e.response.json()
            if e.response.status_code == 400 and error_data.get('error') == 'ExpiredToken' and not is_retry:
                if self._refresh_session():
                    return self._make_request(method, xrpc_endpoint, params, json_data, headers, is_retry=True)
                else: raise e
            else:
                print(f"❌ API error: {error_data.get('message')}")
                raise e

    def get_post_thread(self, post_uri):
        # (This function remains the same)
        try:
            params = {"uri": post_uri, "depth": 2}
            data = self._make_request("GET", "app.bsky.feed.getPostThread", params=params)
            return data.get('thread', {})
        except Exception as e:
            print(f"Error fetching thread for {post_uri}: {e}")
            return None

def get_all_user_posts(handle_and_settings):
    """Fetches posts for a given user. Designed to be called by the thread pool."""
    actor_handle, start_time, end_time, max_posts = handle_and_settings
    print(f"   Starting fetch for @{actor_handle}...")
    all_posts = []
    cursor = None
    
    if start_time is None: start_time = datetime.min.replace(tzinfo=timezone.utc)
    if end_time is None: end_time = datetime.max.replace(tzinfo=timezone.utc)
    
    while True:
        params = {"actor": actor_handle, "limit": 100}
        if cursor: params["cursor"] = cursor

        try:
            response = session._make_request("GET", "app.bsky.feed.getAuthorFeed", params=params)
            posts_on_page = response.get('feed', [])
            if not posts_on_page: break

            for post in posts_on_page:
                try:
                    post_time = datetime.fromisoformat(post['post']['record']['createdAt'].replace("Z", "+00:00"))
                except Exception: continue
                
                if start_time <= post_time <= end_time:
                    post['comments'] = [] 
                    all_posts.append(post)
                    if max_posts and len(all_posts) >= max_posts:
                        print(f"   Reached post limit for @{actor_handle}.")
                        return actor_handle, all_posts
                elif post_time < start_time:
                    print(f"   Reached start time limit for @{actor_handle}.")
                    return actor_handle, all_posts

            cursor = response.get('cursor')
            if not cursor: break
            time.sleep(0.5)

        except Exception as e:
            print(f"Error fetching posts for @{actor_handle}: {e}")
            break
            
    print(f"   ✅ Finished fetching {len(all_posts)} posts for @{actor_handle}.")
    return actor_handle, all_posts

def fetch_comments_and_replies(post_item):
    """Wrapper for threading. Fetches comments for a single post."""
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri: return post_item
    thread = session.get_post_thread(post_uri)
    if thread and 'replies' in thread:
        for comment_thread in thread['replies'][:MAX_COMMENTS_PER_POST]:
            structured_comment = {"post": comment_thread.get('post', {}), "replies": []}
            if 'replies' in comment_thread:
                for reply_thread in comment_thread['replies']:
                    structured_comment["replies"].append(reply_thread.get('post', {}))
            post_item['comments'].append(structured_comment)
    return post_item

if __name__ == "__main__":
    load_dotenv()
    print("--- Bluesky Multi-User Post Archiver (Separate Files) ---")
    
    user_handle = os.environ.get("BSKY_USERNAME")
    app_password = os.environ.get("BSKY_PASSWORD")

    global session
    session = BlueskySession(user_handle, app_password)

    if session.create_session():
        target_handles_input = clean_input(input("\nEnter user handles to fetch (separate with spaces or commas): "))
        target_handles = [h.strip() for h in target_handles_input.replace(',', ' ').split() if h.strip()]

        if not target_handles:
            print("No target handles provided. Exiting.")
            exit()

        start_time, end_time = None, None
        if clean_input(input("\nFilter posts by timestamp? (y/n): ")).lower() == 'y':
            start_input = clean_input(input("Enter start timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            end_input = clean_input(input("Enter end timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            try:
                if start_input: start_time = datetime.strptime(start_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if end_input: end_time = datetime.strptime(end_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                print("⚠️ Invalid date format. Aborting."); exit(1)

        max_posts_input = clean_input(input("Enter max posts to fetch PER USER (blank for all): "))
        max_posts = int(max_posts_input) if max_posts_input.isdigit() else None
        
        print("\n--- Starting Parallel Post Fetch ---")
        total_start_time = time.time()
        
        # --- Create a list of tasks for the executor ---
        tasks = [(handle, start_time, end_time, max_posts) for handle in target_handles]
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # The executor returns results as they are completed
            results = executor.map(get_all_user_posts, tasks)

            # --- MODIFIED: Process and save each user's data individually ---
            for handle, posts in results:
                if not posts:
                    print(f"\nNo posts found for @{handle}. Skipping.")
                    continue

                print(f"\nProcessing {len(posts)} posts for @{handle}...")
                
                # Add clickable URLs
                for item in posts:
                    author_handle = item.get('post', {}).get('author', {}).get('handle')
                    post_uri = item.get('post', {}).get('uri')
                    if author_handle and post_uri:
                        post_id = post_uri.split('/')[-1]
                        item['post']['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

                # Fetch comments in parallel for the current user's posts
                print(f"Fetching comments for @{handle}'s posts...")
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as comment_executor:
                    posts = list(comment_executor.map(fetch_comments_and_replies, posts))

                # Save to a user-specific file
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                safe_handle = handle.replace('.', '_')
                filename = os.path.join("user_model", f"posts_{safe_handle}_{timestamp}.json")
                os.makedirs("multiple_user", exist_ok=True)
                
                print(f"Saving posts for @{handle} to '{filename}'...")
                try:
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(posts, f, ensure_ascii=False, indent=2)
                    print(f"✅ Successfully saved results for @{handle}.")
                except Exception as e:
                    print(f"❌ Failed to save file for @{handle}. Error: {e}")

        print(f"\n✨ --- Total Execution Time: {time.time() - total_start_time:.2f} seconds --- ✨")