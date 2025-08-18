import requests
import os
import time
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import re

# --- Configuration ---
BSKY_HOST = "https://bsky.social"
# Maximum number of comments to fetch for each post
MAX_COMMENTS_PER_POST = 150
# Number of parallel workers for fetching comments
MAX_WORKERS = 10

def clean_input(input_string):
    """
    A robust function to remove all non-printable characters from a string.
    """
    return ''.join(filter(str.isprintable, input_string))

class BlueskySession:
    """
    Manages a session with the Bluesky API, including automatic token refresh.
    """
    def __init__(self, handle, password):
        self._handle = handle
        self._password = password
        self.access_jwt = None
        self.refresh_jwt = None
        self.did = None
        self.session_active = False

    def create_session(self):
        """
        Creates an initial session with the Bluesky server.
        """
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
        """
        Uses the refresh token to get a new access token.
        """
        print("\n⚠️ Access token expired. Refreshing session...")
        if not self.refresh_jwt:
            print("❌ No refresh token available. Cannot refresh session.")
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
        """
        A generic, authenticated request handler that includes automatic token refresh logic.
        """
        if not self.session_active:
            raise Exception("Session is not active. Please create a session first.")

        if headers is None: headers = {}
        headers["Authorization"] = f"Bearer {self.access_jwt}"
        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        
        try:
            response = requests.request(method, full_url, params=params, json=json_data, headers=headers)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.HTTPError as e:
            error_data = e.response.json()
            if e.response.status_code == 400 and error_data.get('error') == 'ExpiredToken' and not is_retry:
                if self._refresh_session():
                    return self._make_request(method, xrpc_endpoint, params=params, json_data=json_data, headers=headers, is_retry=True)
                else:
                    raise e
            else:
                print(f"❌ An API error occurred: {error_data.get('message')}")
                raise e

    def get_post_thread(self, post_uri):
        """
        Fetches a post's full thread, including comments and their replies.
        """
        try:
            params = {"uri": post_uri, "depth": 2} # Depth 2 gets comments and their replies
            data = self._make_request("GET", "app.bsky.feed.getPostThread", params=params)
            return data.get('thread', {})
        except Exception as e:
            print(f"Error fetching thread for {post_uri}: {e}")
            return None

    def search_posts_advanced(self, query, sort_order='latest', max_posts=1000):
        """
        Performs an advanced search for posts with pagination.
        """
        print(f"\nSearching for posts with query: '{query}' (sorted by {sort_order})")
        
        all_posts = []
        cursor = None
        
        while True:
            # Determine the limit for the next request
            limit = 100
            if max_posts:
                limit = min(100, max_posts - len(all_posts))
            
            if max_posts and len(all_posts) >= max_posts:
                print("Reached requested number of posts.")
                break
            if max_posts and limit <= 0:
                break

            params = {"q": query, "sort": sort_order, "limit": limit}
            if cursor:
                params["cursor"] = cursor

            try:
                response = self._make_request("GET", "app.bsky.feed.searchPosts", params=params)
                posts_on_page = response.get('posts', [])
                if not posts_on_page:
                    print("No more posts found for this search. Halting.")
                    break
                
                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(all_posts)} posts so far...")

                cursor = response.get('cursor')
                if not cursor:
                    print("Reached the end of the search results.")
                    break
                
                time.sleep(0.5) # Polite delay

            except Exception as e:
                print(f"An error occurred during fetching: {e}")
                break
        
        return all_posts

# This function will be run in parallel for each post
def fetch_comments_and_replies(post_item):
    """
    Wrapper function for threading. Fetches comments and replies for a single post.
    """
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri:
        return post_item

    print(f"   Fetching comments for post: {post_uri.split('/')[-1]}")
    thread = session.get_post_thread(post_uri)
    
    if thread and 'replies' in thread:
        top_level_comments = thread['replies']
        
        for comment_thread in top_level_comments[:MAX_COMMENTS_PER_POST]:
            comment_post = comment_thread.get('post', {})
            structured_comment = {"post": comment_post, "replies": []}

            if 'replies' in comment_thread:
                for reply_thread in comment_thread['replies']:
                    structured_comment["replies"].append(reply_thread.get('post', {}))
            
            post_item['comments'].append(structured_comment)

    return post_item

if __name__ == "__main__":
    print("--- Bluesky Search Tool (Upgraded) ---")
    
    user_handle = clean_input(input("Enter your Bluesky handle: "))
    app_password = clean_input(input("Enter your App Password: "))

    global session
    session = BlueskySession(user_handle, app_password)

    if session.create_session():
        print("\n--- Build Your Search Query ---")
        
        include_terms = clean_input(input('Enter search terms (use "quotes for exact phrases"): '))
        exclude_terms_raw = clean_input(input('Enter words to EXCLUDE (optional, separate with spaces): '))
        exclude_terms = [f"-{term.strip()}" for term in exclude_terms_raw.split() if term.strip()]
        
        final_query_parts = [include_terms] + exclude_terms
        final_query = " ".join(final_query_parts).strip()
        
        if not final_query:
            print("No search query provided. Exiting.")
            exit()

        while True:
            sort_choice = clean_input(input("Sort by [1] Top or [2] Latest? (Enter 1 or 2): "))
            if sort_choice == '1':
                sort_order = 'top'; break
            elif sort_choice == '2':
                sort_order = 'latest'; break
            else:
                print("Invalid choice. Please enter 1 or 2.")
        
        max_posts_input = clean_input(input("Enter max number of posts to fetch (e.g., 500, or blank for all): "))
        max_posts = int(max_posts_input) if max_posts_input.isdigit() else None

        print("\n--- Starting Benchmark ---")
        total_start_time = time.time()

        # --- 1. Fetching Posts ---
        post_fetch_start = time.time()
        fetched_posts = session.search_posts_advanced(final_query, sort_order, max_posts)
        post_fetch_end = time.time()
        print(f"--- 📊 Fetched {len(fetched_posts)} posts in {post_fetch_end - post_fetch_start:.2f} seconds ---")

        # --- 2. Fetching Comments in Parallel ---
        if fetched_posts:
            # Prepare data for the new structure
            posts_with_comments_placeholder = [{'post': post, 'comments': []} for post in fetched_posts]

            print(f"\nFetching comments for {len(posts_with_comments_placeholder)} posts using {MAX_WORKERS} parallel workers...")
            comment_fetch_start = time.time()
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                results = list(executor.map(fetch_comments_and_replies, posts_with_comments_placeholder))
            
            comment_fetch_end = time.time()
            print(f"--- 📊 Fetched comments in {comment_fetch_end - comment_fetch_start:.2f} seconds ---")
            
            final_posts = results
        else:
            final_posts = []

        total_end_time = time.time()
        print(f"\n✨ --- Total Execution Time: {total_end_time - total_start_time:.2f} seconds --- ✨")
        
        # --- 3. Saving Results ---
        if final_posts:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            # Create a safe filename from the query
            safe_query = re.sub(r'[^a-zA-Z0-9_]', '', final_query.replace(" ", "_"))[:30]

            output_dir = "search_model"
            os.makedirs(output_dir, exist_ok=True)

            filename = os.path.join(output_dir, f"search_{safe_query}_{timestamp}.json")
            
            print(f"\nSaving {len(final_posts)} posts with comments to '{filename}'...")
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(final_posts, f, ensure_ascii=False, indent=2)
                print(f"\n✅ Successfully saved results.")
            except Exception as e:
                print(f"\n❌ Failed to save posts to file. Error: {e}")
        else:
            print("\n⚠️ No posts found or fetched to save.")
