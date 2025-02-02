import csv
import datetime
import http.client
import json
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


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


def data_retrevial():
    country = "es"
    city = input()
    city = normalize_text(city)

    districts = input()

    districts_list = [normalize_text(district.strip()) for district in districts.splitlines() if district.strip()]
    if not districts_list:
        print("null")

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
            # Separate metro zones and regular districts
            metro_zones = [loc for loc in matching_locations if "metro" in loc.get("subType", "").lower()]
            regular_districts = [loc for loc in matching_locations if loc not in metro_zones]

            if metro_zones and regular_districts:
                choices = input(
                    f"Both metro zones and regular districts were found for {district}. Select the locations to include in the search:",
                    "Choose Locations",
                    choices=[f"Metro{city.capitalize()}: {loc['name']}" for loc in metro_zones] +
                            [f"District: {loc['name']}" for loc in regular_districts]
                )
                if choices:
                    district_results[district] = []
                    for choice in choices:
                        if choice.startswith("Metro:"):
                            district_results[district].append(metro_zones.pop(0))
                        elif choice.startswith("District:"):
                            district_results[district].append(regular_districts.pop(0))
            else:
                district_results[district] = metro_zones or regular_districts
                # Display info box for districts without multiple choices
                selected_names = [loc['name'] for loc in district_results[district]]
                print(
                    f"Automatically selected locations for district/metro{city.capitalize()} '{district.capitalize()}':\n" +
                    "\n".join(selected_names)+ "\n"+"ZoI ID: "+str(district_results[district][0].get("zoiId"))+"\n"+"Location ID: "+str(district_results[district][0].get("locationId")),
                    "Selected Locations"
                )
        else:
            print(f"No matches found for district {district.capitalize()}.", "No Match")

    if not district_results:
        print("No matching locations found for any district. Exiting.", "No Match")


    max_price = input("Enter the maximum price (leave blank for no max):")
    min_price = input("Enter the minimum price (leave blank for no min):")
    min_rooms = input("Enter the minimum number of rooms (leave blank for no min):")
    min_rooms = int(min_rooms) if min_rooms else None

    floor_options = ["topFloor", "intermediateFloor", "groundFloor"]
    selected_floors = input(
        "Select the floor types you would consider:",
        "Floor Types",
        floor_options
    )
    floorHeights = ",".join(selected_floors) if selected_floors else None

    air_conditioning = input(
        "Do you require air conditioning?",
        "Air Conditioning",
        ["Yes", "No"]
    )

    elevator = input(
        "Do you require an elevator?",
        "Elevator",
        ["Yes", "No"]
    )

    print("Please wait while we fetch the properties.", "Fetching Properties")

    rresults = []
    for district, locations in district_results.items():
        for location in locations:
            zoiID = location.get("zoiId")
            locationID = location.get("locationId")

            # Use zoiId if available; fallback to locationId if zoiId is missing
            identifier_type = "zoiId" if zoiID else "locationId"
            identifier_value = zoiID or locationID

            if not identifier_value:
                print(f"WARNING: No zoiId or locationId available for location: {location['name']}")
                continue

            print(f"DEBUG: Fetching properties for district {district} and location {location['name']} ({identifier_type}: {identifier_value})")

            query = f"?numPage=1&maxItems=40&sort=asc&locale=en&operation=rent&country={country}&{identifier_type}={identifier_value}"
            if max_price:
                query += f"&maxPrice={max_price}"
            if min_price:
                query += f"&minPrice={min_price}"
            if min_rooms:
                query += f"&minRooms={min_rooms}"
            if floorHeights:
                query += f"&floorHeights={floorHeights}"
            if air_conditioning:
                query += f"&airConditioning=true"
            if elevator:
                query += f"&elevator=true"

            properties_data = get_data("/properties/list", query, headers)

            if 'elementList' in properties_data and properties_data['elementList']:
                for prop in properties_data['elementList']:
                    rresults.append({
                        "rooms": prop.get("rooms", ""),
                        "locationId": prop.get("locationId", ""),
                        "multimedia": prop.get("multimedia", ""),
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

        fieldnames = [
            "rooms", "locationId", "multimedia", "price", "status", "size",
            "address", "bathrooms", "url", "district"
        ]
        with open(output_file, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rresults)

        print(f"Results saved to {output_file}", "Success")
    else:
        print("No properties found with the specified criteria.", "No Properties")



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

@app.route("/")
def homepage():

    return render_template("index.html")

@app.route("/get-house", method="POST")
def get_house():
    data = requests.get("index.html")
    # to do get input from html page
    # fit data into data retrevial function 
    # post_data = data_retrevial(city,rooms,min_price,max_price)
    # retrun jsonify(post_data)
    pass

@app.route( "/results" , method="POST" )
def show_results():
    pass

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