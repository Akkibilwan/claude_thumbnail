import streamlit as st
import os
import io
from PIL import Image
import openai
import base64
import time

# Set page configuration
st.set_page_config(
    page_title="Thumbnail Analyzer",
    page_icon="🔍",
    layout="wide"
)

# Function to setup OpenAI API credentials
def setup_openai_credentials():
    try:
        if 'OPENAI_API_KEY' in st.secrets:
            api_key = st.secrets["OPENAI_API_KEY"]
            return api_key
        else:
            api_key = os.environ.get('OPENAI_API_KEY')
            if api_key:
                return api_key
            else:
                api_key = st.text_input("Enter your OpenAI API key:", type="password")
                if not api_key:
                    st.warning("Please enter an OpenAI API key to continue")
                    return None
                return api_key
    
    except Exception as e:
        st.error(f"Error setting up OpenAI API: {str(e)}")
        return None

# Function to encode image to base64 for OpenAI
def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

# Function to analyze image with OpenAI
def analyze_with_openai(api_key, base64_image):
    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4-vision-preview",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this YouTube thumbnail. Describe what you see in detail."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        st.error(f"Error analyzing image with OpenAI: {e}")
        return None

# Main app
def main():
    st.title("YouTube Thumbnail Analyzer")
    st.write("Upload a thumbnail to analyze it using OpenAI's Vision capabilities.")
    
    # Initialize OpenAI client
    api_key = setup_openai_credentials()
    
    if not api_key:
        return
    
    # File uploader
    uploaded_file = st.file_uploader("Choose a thumbnail image...", type=["jpg", "jpeg", "png"])
    
    if uploaded_file is not None:
        # Display the uploaded image
        image = Image.open(uploaded_file)
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.image(image, caption="Uploaded Thumbnail", use_column_width=True)
        
        # Convert to bytes for API processing
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format=image.format if image.format else 'JPEG')
        img_byte_arr = img_byte_arr.getvalue()
        
        # Process with OpenAI Vision
        with st.spinner("Analyzing thumbnail..."):
            base64_image = encode_image(img_byte_arr)
            analysis = analyze_with_openai(api_key, base64_image)
            
            if analysis:
                with col2:
                    st.subheader("Thumbnail Analysis")
                    st.write(analysis)
                    
                    # Add a download button for the analysis
                    st.download_button(
                        label="Download Analysis",
                        data=analysis,
                        file_name="thumbnail_analysis.txt",
                        mime="text/plain"
                    )

if __name__ == "__main__":
    main()
