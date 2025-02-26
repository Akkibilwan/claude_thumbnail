import streamlit as st
import googleapiclient.discovery
import google.oauth2.credentials
import json
import requests
import os
import sqlite3
import pandas as pd
import time
from datetime import datetime, timedelta
import hashlib
from openai import OpenAI
from google.cloud import vision
import io
import base64
from PIL import Image

# Initialize session state variables if they don't exist
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'selected_video' not in st.session_state:
    st.session_state.selected_video = None
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = {}
if 'page' not in st.session_state:
    st.session_state.page = "search"

# Setup Database
def setup_db():
    conn = sqlite3.connect('youtube_analyzer.db')
    c = conn.cursor()
    
    # Create tables
    c.execute('''
    CREATE TABLE IF NOT EXISTS searches (
        id INTEGER PRIMARY KEY,
        query TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS cache (
        key TEXT PRIMARY KEY,
        data TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS thumbnail_analyses (
        video_id TEXT PRIMARY KEY,
        vision_analysis TEXT,
        gpt_prompt TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    conn.commit()
    return conn

# Cache functions
def get_cache(key):
    conn = setup_db()
    c = conn.cursor()
    
    # Create a hash of the key for storage
    key_hash = hashlib.md5(key.encode()).hexdigest()
    
    c.execute("SELECT data, timestamp FROM cache WHERE key = ?", (key_hash,))
    result = c.fetchone()
    
    if result:
        data, timestamp = result
        timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        # Cache expires after 1 hour
        if datetime.now() - timestamp < timedelta(hours=1):
            conn.close()
            return json.loads(data)
    
    conn.close()
    return None

def set_cache(key, data):
    conn = setup_db()
    c = conn.cursor()
    
    # Create a hash of the key for storage
    key_hash = hashlib.md5(key.encode()).hexdigest()
    
    # Store the data as JSON
    c.execute(
        "INSERT OR REPLACE INTO cache (key, data, timestamp) VALUES (?, ?, ?)",
        (key_hash, json.dumps(data), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    
    conn.commit()
    conn.close()

# Initialize YouTube API client
def get_youtube_client():
    api_key = st.secrets["youtube_api_key"]
    youtube = googleapiclient.discovery.build(
        "youtube", "v3", developerKey=api_key
    )
    return youtube

# Initialize OpenAI client
def get_openai_client():
    return OpenAI(api_key=st.secrets["openai_api_key"])

# Initialize Vision AI client
def get_vision_client():
    return vision.ImageAnnotatorClient.from_service_account_json(
        st.secrets["vision_ai_credentials_path"]
    )

# Search YouTube videos
def search_youtube_videos(keywords, search_type, time_filter=None, finance_region=None):
    youtube = get_youtube_client()
    
    # Create cache key
    cache_key = f"search_{keywords}_{search_type}_{time_filter}_{finance_region}"
    cached_results = get_cache(cache_key)
    
    if cached_results:
        return cached_results
    
    # Set up search parameters
    search_params = {
        'q': keywords,
        'part': 'snippet',
        'maxResults': 50,
        'type': 'video'
    }
    
    # Add time filter if specified
    if time_filter:
        published_after = None
        now = datetime.now()
        
        if time_filter == "24h":
            published_after = now - timedelta(hours=24)
        elif time_filter == "48h":
            published_after = now - timedelta(hours=48)
        elif time_filter == "7d":
            published_after = now - timedelta(days=7)
        elif time_filter == "15d":
            published_after = now - timedelta(days=15)
        elif time_filter == "1m":
            published_after = now - timedelta(days=30)
        
        if published_after:
            # Format for YouTube API: RFC 3339 format
            search_params['publishedAfter'] = published_after.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # Handle finance filter
    if search_type == "finance":
        channel_ids = get_finance_channel_ids(finance_region)
        if channel_ids:
            # We need to make separate requests for each channel and combine results
            all_results = []
            
            for channel_id in channel_ids:
                channel_params = search_params.copy()
                channel_params['channelId'] = channel_id
                
                try:
                    request = youtube.search().list(**channel_params)
                    response = request.execute()
                    
                    # Add channel results to overall results
                    if 'items' in response:
                        all_results.extend(response['items'])
                except Exception as e:
                    st.error(f"Error searching channel {channel_id}: {str(e)}")
            
            # Get video details for all videos found
            video_ids = [item['id']['videoId'] for item in all_results if 'videoId' in item['id']]
            if video_ids:
                videos_data = get_videos_details(video_ids)
                
                # Store in cache
                set_cache(cache_key, videos_data)
                return videos_data
            
            return []
    else:
        # Generic search
        try:
            request = youtube.search().list(**search_params)
            response = request.execute()
            
            if 'items' in response:
                video_ids = [item['id']['videoId'] for item in response['items'] if 'videoId' in item['id']]
                if video_ids:
                    videos_data = get_videos_details(video_ids)
                    
                    # Store in cache
                    set_cache(cache_key, videos_data)
                    return videos_data
        except Exception as e:
            st.error(f"Error searching YouTube: {str(e)}")
    
    return []

# Get finance channels from configuration
def get_finance_channel_ids(region=None):
    # Finance channels dictionary
    finance_channels = {
        "india": {
            "Pranjal Kamra": "UCwAdQUuPT6laN-AQR17fe1g",
            "Ankur Warikoo": "UCHYubNqqsWGTN2SF-y8jPmQ",
            "Shashank Udupa": "UCdUEJABvX8XKu3HyDSczqhA",
            "Finance with Sharan": "UCwVEhEzsjLym_u1he4XWFkg",
            "Akshat Srivastava": "UCqW8jxh4tH1Z1sWPbkGWL4g",
            "Labour Law Advisor": "UCVOTBwF0vnSxMRIbfSE_K_g",
            "Udayan Adhye": "UCLQOtbB1COQwjcCEPB2pa8w",
            "Sanjay Kathuria": "UCTMr5SnqHtCM2lMAI31gtFA",
            "Financially free": "UCkGjGT2B7LoDyL2T4pHsUqw",
            "Powerup Money": "UC_eLanNOt5ZiKkZA2Fay8SA",
            "Shankar Nath": "UCtnItzU7q_bA1eoEBjqcVrw",
            "Wint Weath": "UCggPd3Vf9ooG2r4I_ZNWBzA",
            "Invest aaj for Kal": "UCWHCXSKASuSzao_pplQ7SPw",
            "Rahul Jain": "UC2MU9phoTYy5sigZCkrvwiw"
        },
        "usa": {
            "Graham Stephan": "UCV6KDgJskWaEckne5aPA0aQ",
            "Mark Tilbury": "UCxgAuX3XZROujMmGphN_scA",
            "Andrei Jikh": "UCGy7SkBjcIAgTiwkXEtPnYg",
            "Humphrey Yang": "UCFBpVaKCC0ajGps1vf0AgBg",
            "Brian Jung": "UCQglaVhGOBI0BR5S6IJnQPg",
            "Nischa": "UCQpPo9BNwezg54N9hMFQp6Q",
            "Newmoney": "Newmoney",
            "I will teach you to be rich": "UC7ZddA__ewP3AtDefjl_tWg"
        }
    }
    
    if region == "india":
        return list(finance_channels["india"].values())
    elif region == "usa":
        return list(finance_channels["usa"].values())
    else:
        # Return all finance channels if no specific region is selected
        return list(finance_channels["india"].values()) + list(finance_channels["usa"].values())

# Get detailed information about videos
def get_videos_details(video_ids):
    youtube = get_youtube_client()
    
    # Split video IDs into chunks of 50 (YouTube API limit)
    video_id_chunks = [video_ids[i:i+50] for i in range(0, len(video_ids), 50)]
    
    all_videos = []
    channel_videos = {}  # To track videos by channel
    
    for chunk in video_id_chunks:
        try:
            # Get video details
            videos_request = youtube.videos().list(
                part="snippet,contentDetails,statistics",
                id=",".join(chunk)
            )
            videos_response = videos_request.execute()
            
            # Process each video
            for video in videos_response.get("items", []):
                channel_id = video["snippet"]["channelId"]
                
                # Get video duration
                duration = video["contentDetails"]["duration"]
                
                # Determine if it's a short
                is_short = False
                if "PT" in duration and "M" not in duration:
                    # Parse duration format (e.g., "PT15S" for 15 seconds)
                    seconds = 0
                    if "S" in duration:
                        seconds = int(duration.split("PT")[1].split("S")[0])
                    
                    # Shorts are typically less than 60 seconds
                    if seconds <= 60:
                        is_short = True
                
                # Add to the channel's video list
                if channel_id not in channel_videos:
                    channel_videos[channel_id] = {"shorts": [], "regular": []}
                
                # Store video with its view count
                view_count = int(video["statistics"].get("viewCount", 0))
                
                video_data = {
                    "id": video["id"],
                    "title": video["snippet"]["title"],
                    "channel_id": channel_id,
                    "channel_title": video["snippet"]["channelTitle"],
                    "published_at": video["snippet"]["publishedAt"],
                    "thumbnail_url": video["snippet"]["thumbnails"]["high"]["url"],
                    "view_count": view_count,
                    "is_short": is_short,
                    "outlier_score": 0  # Will be calculated later
                }
                
                if is_short:
                    channel_videos[channel_id]["shorts"].append(video_data)
                else:
                    channel_videos[channel_id]["regular"].append(video_data)
                
                all_videos.append(video_data)
        
        except Exception as e:
            st.error(f"Error fetching video details: {str(e)}")
    
    # Calculate outlier scores for each video
    for channel_id, videos in channel_videos.items():
        # Calculate average views for shorts and regular videos separately
        shorts_avg = 1  # Default to 1 to avoid division by zero
        regular_avg = 1
        
        if videos["shorts"]:
            shorts_avg = sum(v["view_count"] for v in videos["shorts"]) / len(videos["shorts"])
        
        if videos["regular"]:
            regular_avg = sum(v["view_count"] for v in videos["regular"]) / len(videos["regular"])
        
        # Update outlier scores
        for video in all_videos:
            if video["channel_id"] == channel_id:
                if video["is_short"]:
                    video["outlier_score"] = video["view_count"] / shorts_avg if shorts_avg > 0 else 0
                else:
                    video["outlier_score"] = video["view_count"] / regular_avg if regular_avg > 0 else 0
    
    return all_videos

# Analyze thumbnail with Vision AI
def analyze_thumbnail(thumbnail_url):
    conn = setup_db()
    c = conn.cursor()
    
    # Extract video ID from URL
    video_id = thumbnail_url.split("/")[-2]
    
    # Check if analysis exists in database
    c.execute("SELECT vision_analysis, gpt_prompt FROM thumbnail_analyses WHERE video_id = ?", (video_id,))
    result = c.fetchone()
    
    if result:
        conn.close()
        return {"vision_analysis": result[0], "gpt_prompt": result[1]}
    
    # Download the thumbnail image
    response = requests.get(thumbnail_url)
    if response.status_code != 200:
        conn.close()
        return {"error": f"Failed to download thumbnail: {response.status_code}"}
    
    image_content = response.content
    
    # Vision AI analysis
    try:
        # Using Google Vision AI
        vision_client = get_vision_client()
        image = vision.Image(content=image_content)
        
        # Perform label detection
        label_response = vision_client.label_detection(image=image)
        labels = [label.description for label in label_response.label_annotations]
        
        # Perform text detection
        text_response = vision_client.text_detection(image=image)
        texts = []
        if text_response.text_annotations:
            texts = [text_response.text_annotations[0].description]
        
        # Perform object detection
        object_response = vision_client.object_localization(image=image)
        objects = [obj.name for obj in object_response.localized_object_annotations]
        
        # Combine all analyses
        vision_analysis = {
            "labels": labels,
            "text": texts,
            "objects": objects
        }
        
        # Format vision analysis for GPT
        vision_analysis_text = json.dumps(vision_analysis, indent=2)
        
        # Generate prompt with GPT
        openai_client = get_openai_client()
        
        gpt_response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert YouTube thumbnail analyst. Analyze the information from Vision AI and create a comprehensive analysis of what's happening in the thumbnail."},
                {"role": "user", "content": f"Based on this Vision AI analysis of a YouTube thumbnail, describe what is happening in the thumbnail and why it might be engaging: {vision_analysis_text}"}
            ]
        )
        
        gpt_prompt = gpt_response.choices[0].message.content
        
        # Save to database
        c.execute(
            "INSERT OR REPLACE INTO thumbnail_analyses (video_id, vision_analysis, gpt_prompt, timestamp) VALUES (?, ?, ?, ?)",
            (video_id, vision_analysis_text, gpt_prompt, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
        
        return {
            "vision_analysis": vision_analysis_text,
            "gpt_prompt": gpt_prompt
        }
    
    except Exception as e:
        conn.close()
        return {"error": f"Error analyzing thumbnail: {str(e)}"}

# UI Functions
def show_search_page():
    st.title("YouTube Video Analyzer")
    
    # Search options
    search_type = st.radio("Search Type", ["Generic Search", "Finance Niche"], horizontal=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Sort options
        sort_by = st.selectbox("Sort By", ["Views", "Outlier Score"])
    
    with col2:
        # Time filter
        time_filter = st.selectbox(
            "Time Filter", 
            ["All Time", "24 Hours", "48 Hours", "7 Days", "15 Days", "1 Month"]
        )
    
    # Finance region filter (only show if Finance Niche is selected)
    finance_region = None
    if search_type == "Finance Niche":
        finance_region = st.radio(
            "Finance Region", 
            ["Both", "India", "USA"],
            horizontal=True
        )
    
    # Search box
    search_query = st.text_input("Search Keywords")
    
    # Search button
    if st.button("Search"):
        if not search_query:
            st.warning("Please enter search keywords")
            return
        
        with st.spinner("Searching YouTube..."):
            # Convert time filter to API format
            time_filter_api = None
            if time_filter != "All Time":
                if time_filter == "24 Hours":
                    time_filter_api = "24h"
                elif time_filter == "48 Hours":
                    time_filter_api = "48h"
                elif time_filter == "7 Days":
                    time_filter_api = "7d"
                elif time_filter == "15 Days":
                    time_filter_api = "15d"
                elif time_filter == "1 Month":
                    time_filter_api = "1m"
            
            # Convert finance region to API format
            finance_region_api = None
            if finance_region:
                if finance_region == "India":
                    finance_region_api = "india"
                elif finance_region == "USA":
                    finance_region_api = "usa"
                elif finance_region == "Both":
                    finance_region_api = "both"
            
            # Perform search
            search_type_api = "finance" if search_type == "Finance Niche" else "generic"
            results = search_youtube_videos(
                search_query, 
                search_type_api,
                time_filter_api,
                finance_region_api
            )
            
            # Store results in session state
            st.session_state.search_results = results
            
            # Log the search
            conn = setup_db()
            c = conn.cursor()
            c.execute(
                "INSERT INTO searches (query) VALUES (?)",
                (search_query,)
            )
            conn.commit()
            conn.close()
    
    # Show results if available
    if st.session_state.search_results:
        show_search_results(sort_by.lower().replace(" ", "_"))

def show_search_results(sort_by):
    results = st.session_state.search_results
    
    # Filter and sort results
    shorts = [video for video in results if video["is_short"]]
    regular_videos = [video for video in results if not video["is_short"]]
    
    # Sort by selected criteria
    if sort_by == "views":
        shorts.sort(key=lambda x: x["view_count"], reverse=True)
        regular_videos.sort(key=lambda x: x["view_count"], reverse=True)
    else:  # outlier_score
        shorts.sort(key=lambda x: x["outlier_score"], reverse=True)
        regular_videos.sort(key=lambda x: x["outlier_score"], reverse=True)
    
    # Display results in YouTube-like grid layout
    if regular_videos:
        st.subheader("Regular Videos")
        display_video_grid(regular_videos)
    
    if shorts:
        st.subheader("Shorts")
        display_video_grid(shorts)
    
    if not regular_videos and not shorts:
        st.info("No videos found matching your criteria")

def display_video_grid(videos):
    # Display videos in a grid layout (3 columns)
    cols = st.columns(3)
    
    for i, video in enumerate(videos):
        col_index = i % 3
        
        with cols[col_index]:
            # Create YouTube card-like layout
            st.image(
                video["thumbnail_url"],
                use_column_width=True
            )
            
            st.write(f"**{video['title']}**")
            st.write(f"{video['channel_title']}")
            
            # Show views and outlier score
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"Views: {video['view_count']:,}")
            with col2:
                st.write(f"Outlier: {video['outlier_score']:.2f}x")
            
            # Analyze button
            if st.button(f"Analyze Thumbnail", key=f"analyze_{video['id']}"):
                st.session_state.selected_video = video
                st.session_state.page = "analysis"
                st.experimental_rerun()

def show_analysis_page():
    video = st.session_state.selected_video
    
    # Back button
    if st.button("← Back to Results"):
        st.session_state.page = "search"
        st.experimental_rerun()
    
    st.title("Thumbnail Analysis")
    
    # Display the selected video information
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.image(video["thumbnail_url"], use_column_width=True)
    
    with col2:
        st.subheader(video["title"])
        st.write(f"Channel: {video['channel_title']}")
        st.write(f"Views: {video['view_count']:,}")
        st.write(f"Outlier Score: {video['outlier_score']:.2f}x")
        st.write(f"Published: {video['published_at']}")
    
    # Analyze thumbnail
    with st.spinner("Analyzing thumbnail..."):
        analysis_results = analyze_thumbnail(video["thumbnail_url"])
        
        if "error" in analysis_results:
            st.error(analysis_results["error"])
        else:
            # Show Vision AI results
            st.subheader("Vision AI Analysis")
            vision_data = json.loads(analysis_results["vision_analysis"])
            
            # Labels
            if vision_data.get("labels"):
                st.write("**Labels:**")
                st.write(", ".join(vision_data["labels"][:10]))
            
            # Text
            if vision_data.get("text") and vision_data["text"]:
                st.write("**Text detected:**")
                st.write(vision_data["text"][0])
            
            # Objects
            if vision_data.get("objects"):
                st.write("**Objects:**")
                st.write(", ".join(vision_data["objects"]))
            
            # Show GPT analysis
            st.subheader("Thumbnail Analysis")
            st.write(analysis_results["gpt_prompt"])

# Main app
def main():
    # Set page config
    st.set_page_config(
        page_title="YouTube Video Analyzer",
        page_icon="🎬",
        layout="wide"
    )
    
    # Setup database
    setup_db()
    
    # Navigation based on session state
    if st.session_state.page == "search":
        show_search_page()
    elif st.session_state.page == "analysis":
        show_analysis_page()

if __name__ == "__main__":
    main()
