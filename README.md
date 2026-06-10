# collegematcher
CS 199P project
npm --vers

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