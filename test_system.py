#!/usr/bin/env python3
"""
Test script to verify the RSS to WordPress automation system functionality
"""

import sys
import os
from pathlib import Path

# Load environment variables
env_file = Path('.env')
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                value = value.strip('"').strip("'")
                os.environ[key] = value

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.feeds import FeedReader
from app.wordpress import WordPressClient

def test_feed_processing():
    """Test RSS feed processing"""
    print("Testing RSS feed processing...")
    
    feed_reader = FeedReader("RSS-to-WordPress-Bot/1.0")
    
    # Test with ScreenRant feed
    test_url = "https://screenrant.com/feed/"
    entries = feed_reader.read_single_feed(test_url, "screenrant")
    
    if entries:
        print(f"✓ Successfully retrieved {len(entries)} entries from ScreenRant")
        if len(entries) > 0:
            print(f"  First entry: {entries[0].get('title', 'No title')}")
        return True
    else:
        print("✗ Failed to retrieve RSS entries")
        return False

def test_wordpress_connection():
    """Test WordPress connection"""
    print("Testing WordPress connection...")
    
    try:
        wp_client = WordPressClient()
        
        # Test connection by getting categories
        categories = wp_client.get_categories()
        
        if categories:
            print(f"✓ Successfully connected to WordPress")
            print(f"  Found {len(categories)} categories")
            return True
        else:
            print("✗ No categories found, but connection successful")
            return True
            
    except Exception as e:
        print(f"✗ WordPress connection failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=== RSS to WordPress System Test ===\n")
    
    tests_passed = 0
    total_tests = 2
    
    if test_feed_processing():
        tests_passed += 1
    
    print()
    
    if test_wordpress_connection():
        tests_passed += 1
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {tests_passed}/{total_tests}")
    
    if tests_passed == total_tests:
        print("✓ All tests passed! System is ready for automation.")
    else:
        print("✗ Some tests failed. Check configuration and credentials.")

if __name__ == "__main__":
    main()