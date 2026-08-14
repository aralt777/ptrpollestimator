import json
import os
from pathlib import Path

import requests
from voting import apportionment

BASE = "https://api.ptr.zanz2.dev/api"

NATION_ID = 1          # Change per country
PARTY_ID = 71        # Your party ID

NATION_MAPPING = {
    1: "beluzia",
    2: "kalopia",
    3: "rilandor",
    4: "hulstriaandgaosoto",
    5: "davostag",
    6: "dundorf",
    7: "vanuku",
    8: "saridan"
}

country_name = NATION_MAPPING.get(NATION_ID)

base_dir = Path(__file__).parent
country_file = base_dir / "countries" / f"{country_name}.json"

with open(country_file, "r") as f:
    country = json.load(f)

def auth_headers():
    token = "INSERT_TOKEN_HERE"

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

def get_parties(headers):
    r = requests.get(
        f"{BASE}/parties/?nation_id={NATION_ID}",
        headers=headers
    )

    r.raise_for_status()

    parties = r.json()

    return [
        party
        for party in parties
        if party["is_active"]
    ]

    
headers = auth_headers()

party_data = get_parties(headers)

party_ids = [
    party["abbreviation"]
    for party in party_data
]

party_names = {
    party["abbreviation"]: party["name"]
    for party in party_data
}

party_seats = {
    party["abbreviation"]: party["seat_count"]
    for party in party_data
}

def list_polls(headers):
    # Ensure there is only one slash between BASE and nations
    r = requests.get(
        f"{BASE}/nations/{NATION_ID}/polls",
        headers=headers,
        params={"party_id": PARTY_ID}
    )
    if r.status_code == 422:
        print("Validation Error Detail from Server:")
        print(r.text)
    r.raise_for_status()
    return r.json()


def get_poll(headers, poll_id):
    r = requests.get(
        f"{BASE}/nations/{NATION_ID}/polls/{poll_id}",
        headers=headers
    )
    r.raise_for_status()
    return r.json()

def build_polls(country, detail):

    polls = {}

    for group in detail["groups"]:

        # API returns parties sorted by support
        party_support = {
            party["abbreviation"]: party["support_pct"]
            for party in group["party_support"]
        }

        # Rebuild in the order your simulator expects
        ordered_poll = [
            party_support.get(pid, 0)
            for pid in party_ids
        ]

        # Find matching region
        region = next(
            r
            for r in country["regions"]
            if r["name"] == group["group_name"]
        )

        polls[region["id"]] = ordered_poll

    return polls


headers = auth_headers()

available_polls_response = list_polls(headers)

# Access the list of polls inside the "items" key
available_polls = available_polls_response.get("items", [])

# Allowed dimensions defined by your target options
target_dimensions = {"territory", "settlement", "sex_age", "structural", "religion", "ethnicity"}

# 3. Filter available polls to make sure they match one of your supported groups
valid_polls = [
    poll for poll in available_polls 
    if poll.get("dimension") in target_dimensions
]

if not valid_polls:
    raise Exception("No matching multi-dimension polls found.")

# 4. Prompt the user to enter a specific Poll ID
print("Available matching polls:")
for p in valid_polls:
    # Safely extract game_month or provide a fallback if it isn't set
    game_month = p.get("game_month", "N/A")
    print(f" - ID: {p.get('id'):<5} | Dimension: {p.get('dimension'):<12} | Date: {game_month}")

while True:
    try:
        user_choice = int(input("\nEnter the Poll ID you want to run: "))
        # Find the selected poll in our valid polls list
        active_poll = next((p for p in valid_polls if p.get("id") == user_choice), None)
        
        if active_poll:
            poll_id = active_poll["id"]
            break
        else:
            print("That ID does not match any available valid polls. Please try again.")
    except ValueError:
        print("Invalid input. Please enter a numerical ID.")

# 5. Extract the dimension string DIRECTLY from the server's poll data
active_dimension = active_poll["dimension"]
print(f"Detected Poll Dimension from Server: {active_dimension}")

# 6. Dynamically update your country object configuration block
if active_dimension in country.get("dimensions", {}):
    country["regions"] = country["dimensions"][active_dimension]
else:
    raise Exception(f"Dimension '{active_dimension}' configuration missing from your JSON file!")

# 7. Resume the script's normal data gathering execution flow
detail = get_poll(headers, poll_id)
polls = build_polls(country, detail)

for region in country["regions"]:
    region["poll"] = polls[region["id"]]

for region in country["regions"]:
    total = sum(region["poll"])

    region["normalised"] = [
        vote / total
        for vote in region["poll"]
    ]

national_vote = [0] * len(party_ids)

for region in country["regions"]:
    for i, vote in enumerate(region["normalised"]):
        national_vote[i] += vote * region["weight"]

vote_dictionary = {}

# 1. Remove party_seats from zip() so we don't accidentally pull text keys
for party_id, vote in zip(party_ids, national_vote):
    
    # 2. Safely look up the previous seats using the party_id string
    # If party_seats is a dict, this grabs the number. If it's a list, use int(party_seats[party_ids.index(party_id)])
    if isinstance(party_seats, dict):
        c_seat = party_seats.get(party_id, 0)
    else:
        # Fallback if it's a list/sequence matching party_ids order
        idx = party_ids.index(party_id)
        c_seat = party_seats[idx]

    vote_dictionary[party_id] = {
        "votes": int(vote * 100000),
        "current_seats": int(c_seat)  # Clean integer conversion
    }
total_votes = sum(data["votes"] for data in vote_dictionary.values())

filtered_votes = {
    party: data
    for party, data in vote_dictionary.items()
    if data["votes"] / total_votes >= country["threshold"]
}

votes = [data["votes"] for data in filtered_votes.values()]

if country["system"] == "sainte_lague":
    seat_list = apportionment.sainte_lague(
        votes,
        country["total_seats"]
    )

elif country["system"] == "dhondt":
    seat_list = apportionment.dhondt(
        votes,
        country["total_seats"]
    )
elif country["system"] == "hare-lr":
    seat_list = apportionment.hamilton(
        votes,
        country["total_seats"]
    )

party_names = list(filtered_votes.keys())

seat_allocations = dict(zip(party_names, seat_list))

sorted_seats = sorted(
    seat_allocations.items(), 
    key=lambda x: (filtered_votes[x[0]]["votes"], x[1]), 
    reverse=True
)

party_order = list(vote_dictionary.keys())

header = f"{'PARTY':<6} "

for region in country["regions"]:
    header += f"{region['id'] + ' %':<8}"

header += f"{'NAT %':<8} {'SEATS':<5} {'+/-':<6}"

print(header)
print("-" * len(header))

sorted_parties = sorted(
    vote_dictionary.items(),
    key=lambda x: x[1]["votes"],
    reverse=True
)

for party, data in sorted_parties:

    idx = party_order.index(party)

    row = f"{party:<6} "

    for region in country["regions"]:
        pct = region["normalised"][idx] * 100
        row += f"{pct:>6.2f}% "
    party_votes = data["votes"]
    current_seats = data["current_seats"]

    nat_pct = party_votes / total_votes * 100
    seats = seat_allocations.get(party, 0)
    status = "*" if party not in filtered_votes else " "
    changevalue = seats - current_seats

    if changevalue > 0:
        change_str = f"+{changevalue}"
    elif changevalue < 0:
        change_str = f"{changevalue}"  
    else:
        change_str = "="

    row += f"{nat_pct:>6.2f}%{status} {seats:>5} {change_str:>4}"

    print(row)

if country["threshold"] > 0:
    print(
        f"\n* Party failed to cross the {country['threshold'] * 100:.0f}% national threshold."
    )
