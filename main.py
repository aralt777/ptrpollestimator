import json
import os
from pathlib import Path

import requests
from voting import apportionment

BASE = "https://api.ptr.zanz2.dev/api"

NATION_ID = 1          # Change per country
PARTY_ID = 71        # Your party ID

country_name = "beluzia"

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
            party_support.get(party["id"], 0)
            for party in country["parties"]
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

# Target the 'territory' dimension as indicated by your server payload
regional_polls = [
    poll
    for poll in available_polls
    if poll["dimension"] == "territory"
]

if not regional_polls:
    raise Exception("No regional polls found.")

# Access the dictionary inside the list index cleanly
poll_id = regional_polls[0]["id"]

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

national_vote = [0] * len(country["parties"])

for region in country["regions"]:
    for i, vote in enumerate(region["normalised"]):
        national_vote[i] += vote * region["weight"]

vote_dictionary = {}

for party, vote in zip(country["parties"], national_vote):
    vote_dictionary[party["id"]] = int(vote * 100000)

total_votes = sum(vote_dictionary.values())

filtered_votes = {
    party: votes
    for party, votes in vote_dictionary.items()
    if votes / total_votes >= country["threshold"]
}

votes = list(filtered_votes.values())

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

party_names = list(filtered_votes.keys())

seat_allocations = dict(zip(party_names, seat_list))

sorted_seats = sorted(
    seat_allocations.items(), 
    key=lambda x: (filtered_votes[x[0]], x[1]), 
    reverse=True
)

party_order = list(vote_dictionary.keys())

header = f"{'PARTY':<6} "

for region in country["regions"]:
    header += f"{region['id'] + ' %':<7}"

header += f"{'NAT %':<7} {'SEATS':<5}"

print(header)
print("-" * len(header))

sorted_parties = sorted(
    vote_dictionary.items(),
    key=lambda x: x[1],
    reverse=True
)

for party, votes in sorted_parties:

    idx = party_order.index(party)

    row = f"{party:<6} "

    for region in country["regions"]:
        pct = region["normalised"][idx] * 100
        row += f"{pct:>5.1f}% "

    nat_pct = votes / total_votes * 100

    seats = seat_allocations.get(party, 0)
    status = "*" if party not in filtered_votes else " "

    row += f"{nat_pct:>5.1f}%{status} {seats:>5}"

    print(row)

if country["threshold"] > 0:
    print(
        f"\n* Party failed to cross the {country['threshold'] * 100:.0f}% national threshold."
    )