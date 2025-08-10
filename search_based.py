import requests
import os
import time
import getpass
import json
from datetime import datetime, timedelta

# --- Configuration ---
BSKY_HOST = "https://bsky.social"

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
        (Compatible with Python < 3.8 — no walrus operator)
        """
        if not self.session_active:
            raise Exception("Session is not active. Please create a session first.")

        if headers is None:
            headers = {}
        headers["Authorization"] = f"Bearer {self.access_jwt}"
        full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
        
        try:
            response = requests.request(method, full_url, params=params, json=json_data, headers=headers)
            response.raise_for_status()
            if response.content:
                return response.json()
            return None
        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            if resp is not None:
                error_data = resp.json()
                if resp.status_code == 400 and error_data.get('error') == 'ExpiredToken' and not is_retry:
                    if self._refresh_session():
                        return self._make_request(method, xrpc_endpoint, params=params, json_data=json_data, headers=headers, is_retry=True)
                    else:
                        raise e
                else:
                    print(f"❌ An API error occurred: {error_data.get('message')}")
                    raise e
            else:
                raise e

    def search_posts_advanced(self, query, sort_order='latest', max_posts=1000):
        """
        Performs an advanced search for posts with pagination.
        """
        print(f"\nSearching for posts with query: '{query}' (sorted by {sort_order})")
        print(f"Fetching up to {max_posts} posts...")
        
        all_posts = []
        cursor = None
        
        while len(all_posts) < max_posts:
            limit = min(100, max_posts - len(all_posts))
            if limit <= 0:
                break

            params = {
                "q": query,
                "sort": sort_order,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor

            try:
                response = self._make_request("GET", "app.bsky.feed.searchPosts", params=params)
                
                posts_on_page = response.get('posts', [])
                if not posts_on_page:
                    print("No more posts found for this search. Halting.")
                    break
                
                all_posts.extend(posts_on_page)
                print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")

                cursor = response.get('cursor')
                if not cursor:
                    print("Reached the end of the search results.")
                    break
                
                time.sleep(1)

            except Exception as e:
                print(f"An error occurred during fetching: {e}")
                break
        
        return all_posts

if __name__ == "__main__":
    print("--- Bluesky Advanced Discovery Tool ---")
    
    user_handle = clean_input(input("Enter your Bluesky handle: "))
    app_password = clean_input(input("Enter your App Password: "))

    session = BlueskySession(user_handle, app_password)
    if session.create_session():
        print("\n--- Build Your Search Query ---")
        
        include_terms = clean_input(input('Enter search terms (you can use "quotes for exact phrases"): '))
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
                sort_order = 'top'
                break
            elif sort_choice == '2':
                sort_order = 'latest'
                break
            else:
                print("Invalid choice. Please enter 1 or 2.")
        
        while True:
            try:
                num_posts = int(input("How many posts do you want to fetch? (e.g., 500): "))
                if num_posts > 0:
                    break
                else:
                    print("Please enter a number greater than 0.")
            except ValueError:
                print("Invalid input. Please enter a whole number.")

        fetched_posts = session.search_posts_advanced(final_query, sort_order, num_posts)
        
        final_posts = []
        lang_choice = clean_input(input("\nFilter by language? (Enter 2-letter code like 'en', 'es', or leave blank for all): ")).lower()
        if not lang_choice:
            final_posts = fetched_posts
            print("No language filter applied.")
        else:
            for post in fetched_posts:
                record = post.get('record', {})
                langs = record.get('langs', [])
                if langs and lang_choice in langs:
                    final_posts.append(post)
            print(f"Filtered down to {len(final_posts)} posts in language '{lang_choice}'.")

        print(f"\n✨ --- Processing Complete --- ✨")
        print(f"Total posts after language filtering: {len(final_posts)}")

        if final_posts:
            ts_filter_choice = clean_input(input("\nDo you want date-based filtering? (yes/no): ")).lower()
            if ts_filter_choice in ['yes', 'y']:
                while True:
                    try:
                        lower_limit = datetime.min
                        upper_limit = datetime.now()

                        lower_limit_str = clean_input(input("Enter LOWER date limit (YYYY-MM-DD) or press Enter for no limit: ")).strip()
                        if lower_limit_str:
                            lower_limit = datetime.strptime(lower_limit_str, "%Y-%m-%d")

                        upper_limit_str = clean_input(input("Enter UPPER date limit (YYYY-MM-DD) or press Enter for no limit: ")).strip()
                        if upper_limit_str:
                            upper_limit = datetime.strptime(upper_limit_str, "%Y-%m-%d")

                        filtered_by_time = []
                        for post in final_posts:
                            created_at_str = post.get('record', {}).get('createdAt')
                            if created_at_str:
                                post_date = datetime.strptime(created_at_str.split("T")[0], "%Y-%m-%d")
                                if lower_limit.date() <= post_date.date() <= upper_limit.date():
                                    filtered_by_time.append(post)

                        print(f"📅 Date filter applied. Remaining posts: {len(filtered_by_time)}")
                        final_posts = filtered_by_time
                        break

                    except ValueError as ve:
                        print(f"❌ Invalid date format: {ve}. Please use YYYY-MM-DD.")

        # --- Save results to file ---
        if final_posts:
            import os
            os.makedirs("results", exist_ok=True)
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join("results", f"bluesky_results_{timestamp_str}.json")

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(final_posts, f, indent=2, ensure_ascii=False)

            print(f"\n💾 Results saved to: {output_file}")
        else:
            print("\n⚠️ No posts to save.")
