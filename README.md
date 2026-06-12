# College Matcher

CS 199P project — a Flask + vanilla JS app that helps a student figure out which colleges fit their academic profile.

## Running it

```
pip install -r requirements.txt
python3 app.py
```

Then open http://localhost:8080.

## Pages

- **Search** (`/`) — enter your GPA, test scores, and academic profile to get a Match Score and Reach/Target/Safety category for every school.
- **My List** (`/recommendations`) — a balanced application list (Reach, Target, Safety) generated from your saved profile.
- **Decisions** (`/decisions`) — randomized admissions-decision simulation for your application list.
- **Browse** (`/browse`) — browse all 70 schools with filters for location, public/private, and test-optional policy (no profile needed).
- **Map** (`/map`) — every school plotted on a map of the US, color-coded by application category if you have a saved profile.
- **Compare** (`/compare`) — pick two schools to see them side by side, including admissions factors and which one you'd have a better chance at.
- **College detail** (`/college/<slug>`) — full admissions stats and factor breakdown for a single school.

A shared nav bar at the top of every page links between all of these.

## Data

`colleges.csv` holds 70 schools with admitted-student GPA/SAT/ACT ranges, location, type, selectivity tier, Common Data Set Section C7 admissions-factor ratings, and lat/lng coordinates for the map.

## How the Match Score Works

Each college page (and search result) shows a **Match Score** (0-100%) estimating how well a student's profile lines up with a school's admitted-student stats and stated admissions priorities.

For each profile field the student fills in, College Matcher computes a 0-100 subscore:

- **GPA**: 100 if above the school's 75th-percentile GPA, 75 if within the middle 50% range, 40 if below the 25th percentile.
- **Test scores (SAT/ACT)**: same 3-tier logic (100 / 75 / 40) based on the school's middle-50% test score range.
- **Class rank**: Top 10% = 100, Top 25% = 80, Top 50% = 60, Not ranked = 50, Bottom 50% = 30.
- **Extracurricular activities**: based on the tier of the student's most impressive activity — Tier 1 (national/international) = 100, Tier 2 = 80, Tier 3 = 60, Tier 4 = 40.
- **Rigor of secondary school record**: `(AP/IB/Honors courses taken ÷ offered) × 100`, falling back to `taken × 10` if "offered" isn't provided. Students from rural or underserved/Title I schools get a +15 context bonus, since admissions readers evaluate rigor relative to what's available at a student's school. Capped at 100.

Each subscore is then weighted by how important that factor is to the specific school, based on its Common Data Set Section C7 rating:

- Very Important = 3
- Important = 2
- Considered = 1
- Not Considered = 0

The final Match Score is the weighted average of all subscores the student has data for, rounded to the nearest whole percent. If a student hasn't filled out any profile fields, no match score is shown.
