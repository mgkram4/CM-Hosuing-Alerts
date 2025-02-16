import csv
import datetime
import http.client
import json
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)
app.secret_key = 'b9c10ee9d8d53b0e9d83e3931e4d8b6a'  # Replace with a secure secret key


def get_data(endpoint, query, headers):
    conn = http.client.HTTPSConnection("idealista2.p.rapidapi.com")
    conn.request("GET", f"{endpoint}{query}", headers=headers)
    res = conn.getresponse()
    data = res.read().decode("utf-8")
    print(f"DEBUG: Response from {endpoint}{query}: {data}")
    return json.loads(data)

def normalize_text(text):
    return unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8').lower()

headers = {
    'x-rapidapi-key': "dc63fbdbeamshc8ad9c30ef2b375p12ee33jsnd4a9b1aa3a01",
    'x-rapidapi-host': "idealista2.p.rapidapi.com"
}


def data_retrevial(city, districts, max_price=None, min_price=None, min_rooms=None, 
                   floor_types=None, elevator=None):
    country = "es"
    city = normalize_text(city)
    districts_list = [normalize_text(district.strip()) for district in districts.splitlines() if district.strip()]
    
    if not districts_list:
        return {"error": "No districts provided"}

    district_results = {}
    for district in districts_list:
        query_district = quote(district)
        auto_complete_data = get_data("/auto-complete", f"?prefix={query_district}&country={country}", headers)

        if not auto_complete_data.get('locations'):
            continue

        matching_locations = [
            item for item in auto_complete_data['locations']
            if normalize_text(item.get("name", "")).find(district) != -1 and
            normalize_text(item.get("name", "")).find(city) != -1
        ]

        if matching_locations:
            metro_zones = [loc for loc in matching_locations if "metro" in loc.get("subType", "").lower()]
            regular_districts = [loc for loc in matching_locations if loc not in metro_zones]
            district_results[district] = metro_zones + regular_districts
            
            selected_names = [loc['name'] for loc in district_results[district]]
            print(f"Selected locations for {district.capitalize()}:\n" + "\n".join(selected_names))
        else:
            print(f"No matches found for district {district.capitalize()}")

    if not district_results:
        return {"error": "No matching locations found for any district"}

    rresults = []
    for district, locations in district_results.items():
        for location in locations:
            zoiID = location.get("zoiId")
            locationID = location.get("locationId")

            identifier_type = "zoiId" if zoiID else "locationId"
            identifier_value = zoiID or locationID

            if not identifier_value:
                print(f"WARNING: No zoiId or locationId available for location: {location['name']}")
                continue

            query = f"?numPage=1&maxItems=40&sort=asc&locale=en&operation=rent&country={country}&{identifier_type}={identifier_value}"
            if max_price:
                query += f"&maxPrice={max_price}"
            if min_price:
                query += f"&minPrice={min_price}"
            if min_rooms:
                query += f"&minRooms={min_rooms}"
            if floor_types:
                query += f"&floorHeights={','.join(floor_types)}"
            if elevator == "yes":
                query += f"&elevator=true"

            properties_data = get_data("/properties/list", query, headers)

            if 'elementList' in properties_data and properties_data['elementList']:
                for prop in properties_data['elementList']:
                    rresults.append({
                        "rooms": prop.get("rooms", ""),
                        "locationId": prop.get("locationId", ""),
                        "multimedia": prop.get("multimedia", []),
                        "price": prop.get("price", ""),
                        "status": prop.get("status", ""),
                        "size": prop.get("size", ""),
                        "address": prop.get("address", ""),
                        "bathrooms": prop.get("bathrooms", ""),
                        "url": prop.get("url", ""),
                        "district": district
                    })

    if rresults:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"results_{timestamp}.csv"

        fieldnames = ["rooms", "locationId", "multimedia", "price", "status", "size",
                     "address", "bathrooms", "url", "district"]
        with open(output_file, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rresults)

        # Get the first result's IDs for display
        first_location = next(iter(district_results.values()))[0]
        return {
            "success": True,
            "results": rresults,
            "file": output_file,
            "zoi_id": first_location.get("zoiId", "N/A"),
            "location_id": first_location.get("locationId", "N/A")
        }
    else:
        return {
            "error": "No properties found with the specified criteria",
            "zoi_id": "N/A",
            "location_id": "N/A"
        }



# Global variable to store the latest results
latest_results = []
previous_results = []

def check_new_listings():
    """Function to check for new listings and compare with previous results"""
    global latest_results, previous_results
    
    # Get the most recent results file
    results_dir = Path('.')
    result_files = list(results_dir.glob('results_*.csv'))
    if not result_files:
        return
    
    latest_file = max(result_files, key=lambda x: x.stat().st_mtime)
    
    # Read the latest results
    new_results = []
    with open(latest_file, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        new_results = list(reader)
    
    # Compare with previous results to find new listings
    new_listings = []
    if previous_results:
        existing_urls = {item['url'] for item in previous_results}
        new_listings = [item for item in new_results if item['url'] not in existing_urls]
    
    # Update the global variables
    previous_results = latest_results
    latest_results = new_results
    
    return new_listings

@app.route("/", methods=['GET', 'POST'])
def homepage():
    if request.method == 'POST':
        city = request.form.get('city')
        districts = request.form.get('districts')
        
        # First form submission (city and districts)
        if 'get-city' in request.form:
            results = data_retrevial(
                city=city,
                districts=districts
            )
            
            # Format the location data for the template
            location_data = {
                'city': city,
                'district': districts,
                'description': f"Search results for {city}",
                'ZOI': results.get('zoi_id', 'N/A'),
                'ID': results.get('location_id', 'N/A'),
                'show_results': True  # Flag to show the results section
            }
            return render_template("index.html", **location_data)
    
    return render_template("index.html", show_results=False)

@app.route("/result", methods=['GET', 'POST'])
def result_page():
    if request.method == 'POST':
        city = request.form.get('city')
        districts = request.form.get('districts')
        max_price = request.form.get('max_price')
        min_price = request.form.get('min_price')
        min_rooms = request.form.get('min_rooms')
        floor_types = request.form.getlist('floor_types')
        elevator = request.form.get('elevator')
        
        results = data_retrevial(
            city=city,
            districts=districts,
            max_price=max_price,
            min_price=min_price,
            min_rooms=min_rooms,
            floor_types=floor_types,
            elevator=elevator
        )
        
        # Process multimedia data before passing to template
        processed_results = []
        for result in results.get('results', []):
            multimedia = result.get('multimedia', [])
            # Ensure multimedia is a list and contains valid data
            if isinstance(multimedia, str):
                multimedia = [multimedia]
            elif isinstance(multimedia, dict):
                multimedia = [multimedia]
            elif not isinstance(multimedia, list):
                multimedia = []
                
            result['multimedia'] = multimedia
            processed_results.append(result)
        
        return render_template("result.html",
                             city=city,
                             results=processed_results,
                             result_count=len(processed_results))
    
    return redirect(url_for('homepage'))




@app.route("/submit-preferences", methods=['POST'])
def submit_preferences():
    # Handle the second form submission (preferences)
    max_price = request.form.get('max_price')
    min_price = request.form.get('min_price')
    min_rooms = request.form.get('min_rooms')
    floor_types = request.form.getlist('floor_types')  # Gets multiple checkbox values
    elevator = request.form.get('elevator')
    
    # Process the preferences and search for properties
    # You'll need to integrate this with your existing property search logic
    
    return redirect(url_for('result'))

@app.route("/api/properties")
def get_properties():
    """Endpoint to get all current properties"""
    global latest_results
    return jsonify(latest_results)

@app.route("/api/new-listings")
def get_new_listings():
    """Endpoint to get only new listings since last check"""
    new_listings = check_new_listings()
    return jsonify(new_listings if new_listings else [])

def init_scheduler():
    """Initialize the scheduler for hourly checks"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=check_new_listings, trigger="interval", hours=1)
    scheduler.start()

if __name__ == "__main__":
    # Initialize the scheduler before running the app
    init_scheduler()
    app.run(debug=True)