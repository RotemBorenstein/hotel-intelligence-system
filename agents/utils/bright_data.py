"""
Bright Data SERP API Integration

Provides web search functionality using Bright Data's SERP API.
Uses direct REST API calls (works on Databricks, no asyncio issues).
"""

import os
import time
import urllib.parse
import requests
from typing import Optional

# Simple in-memory cache to reduce API usage
_CACHE = {}
_CACHE_TTL_SEC = 60 * 30  # 30 minutes


def _cache_get(key: str):
    """Get value from cache if not expired."""
    item = _CACHE.get(key)
    if not item:
        return None
    value, ts = item
    if time.time() - ts > _CACHE_TTL_SEC:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value):
    """Set value in cache with timestamp."""
    _CACHE[key] = (value, time.time())


def search_google_serp(
    query: str,
    num_results: int = 10,
    country: str = "us"
) -> dict:
    """
    Search Google using Bright Data's SERP API (direct REST, no MCP).
    
    Args:
        query: Search query string
        num_results: Number of results to return (default 10)
        country: Country code for geo-targeting (default "us")
    
    Returns:
        dict with keys:
            - success: bool
            - results: list of dicts with title, snippet, link
            - error: str (if success is False)
    """
    api_token = os.getenv("BRIGHTDATA_API_TOKEN")
    if not api_token:
        return {
            "success": False,
            "results": [],
            "error": "BRIGHTDATA_API_TOKEN not found in environment"
        }

    # Check cache first
    cache_key = f"serp::{query.lower()}::{num_results}"
    cached = _cache_get(cache_key)
    if cached:
        print(f"[BrightData SERP] Cache hit for: {query[:50]}...")
        return cached

    base_url = os.getenv("BRIGHTDATA_BASE_URL", "https://api.brightdata.com/request")
    zone = os.getenv("BRIGHTDATA_ZONE", "serp_api3")
    format_type = os.getenv("BRIGHTDATA_SERP_FORMAT", "json")

    encoded_query = urllib.parse.quote(query)
    google_url = f"https://www.google.com/search?q={encoded_query}&num={num_results}&hl=en"
    
    print(f"[BrightData SERP] Searching: {query[:50]}...")
    
    try:
        response = requests.post(
            base_url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json"
            },
            json={
                "zone": zone,
                "url": google_url,
                "format": format_type
            },
            timeout=30
        )
        
        if response.status_code == 200:
            if format_type.lower() == "json":
                data = response.json()
            else:
                data = {"raw": response.text}

            # BrightData /request often wraps payload under "body"
            if isinstance(data, dict) and "body" in data:
                body = data.get("body", "")
                if isinstance(body, dict):
                    data = body
                elif isinstance(body, str):
                    try:
                        import json
                        data = json.loads(body)
                    except Exception:
                        data = {"raw": body}

            # Extract results from various possible formats
            results = []
            
            # Try organic results (standard SERP API format)
            if "organic" in data:
                for item in data["organic"][:num_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "snippet": item.get("description", item.get("snippet", ""))[:300],
                        "link": item.get("link", item.get("url", ""))
                    })
            
            # Try results array
            elif "results" in data:
                for item in data["results"][:num_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", item.get("description", ""))[:300],
                        "link": item.get("link", item.get("url", ""))
                    })
            
            # Fallback: parse raw HTML/text if present
            elif "raw" in data:
                raw = data["raw"]
                # Try to extract snippets from raw content
                import re
                # Look for text blocks that look like search results
                snippets = re.findall(r'[A-Z][^.!?]*(?:review|hotel|wifi|guest|stay|room|service|clean)[^.!?]*[.!?]', raw, re.IGNORECASE)
                for i, snippet in enumerate(snippets[:num_results]):
                    if len(snippet) > 30:
                        results.append({
                            "title": f"Result {i+1}",
                            "snippet": snippet[:300],
                            "link": ""
                        })
            
            result = {
                "success": True,
                "results": results,
                "error": None
            }
            
            # Cache successful results
            if results:
                _cache_set(cache_key, result)
            
            print(f"[BrightData SERP] Found {len(results)} results")
            return result
            
        else:
            error_msg = f"SERP API failed: {response.status_code} - {response.text[:200]}"
            print(f"[BrightData SERP] Error: {error_msg}")
            return {
                "success": False,
                "results": [],
                "error": error_msg
            }
            
    except requests.Timeout:
        return {
            "success": False,
            "results": [],
            "error": "SERP API request timed out (30s)"
        }
    except Exception as e:
        return {
            "success": False,
            "results": [],
            "error": f"SERP API error: {str(e)}"
        }


def format_serp_results(results: list, topic_keywords: list = None) -> str:
    """
    Format SERP results into a readable string for the agent.
    Optionally prioritizes results containing topic keywords.
    
    Args:
        results: List of result dicts with title, snippet, link
        topic_keywords: Optional list of keywords to prioritize
    
    Returns:
        Formatted string of results
    """
    if not results:
        return "No results found."
    
    # Optionally sort by relevance to topic
    if topic_keywords:
        def relevance_score(r):
            text = (r.get("title", "") + " " + r.get("snippet", "")).lower()
            return sum(1 for kw in topic_keywords if kw.lower() in text)
        
        results = sorted(results, key=relevance_score, reverse=True)
    
    output = f"=== Google Search Results ({len(results)} found) ===\n\n"
    
    for i, r in enumerate(results, 1):
        output += f"[{i}] {r.get('title', 'No title')}\n"
        output += f"    Snippet: {r.get('snippet', 'No snippet')}\n"
        if r.get('link'):
            output += f"    URL: {r.get('link')}\n"
        output += "\n"
    
    return output
