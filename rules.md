# WeGro Investor Segmentation --- Calculation Guide

This document explains **what each calculated field means, what it is
calculated from, and how the calculation works** in the Investor
Segmentation pipeline.

The source code describes a pipeline that takes the IR team's raw
order/investment export and produces investor-level segmentation
including investor tier, favorite product category, preferred tenure,
activity status, and product + tenure performance.

------------------------------------------------------------------------

## 1. Input Data

The system expects these required columns:

-   `status`
-   `customer_unique_id`
-   `customer_name`
-   `base_grand_total`
-   `project_name`
-   `tenure`
-   `order_created_at`
-   `invested_created_at`
-   `id`

The system also recognizes these date columns when present:

-   `customer_created_at`
-   `order_created_at`
-   `invested_created_at`
-   `returned_created_at`
-   `close_date`
-   `bank_attachment_date`

------------------------------------------------------------------------

## 2. Data Filtering Before Calculations

### Valid investment rows

Only rows whose `status` is one of the following are included:

-   `invested`
-   `disbursement_running`
-   `closed`

So:

``` text
Valid rows = rows where status ∈ {invested, disbursement_running, closed}
```

Rows with any other status are excluded.

### Optional start-date filter

If the user enables the start-date filter:

``` text
Keep rows where order_created_at >= selected start date
```

The date filter is based on `order_created_at`.

### Date conversion

The recognized date columns are converted to dates using pandas date
parsing.

------------------------------------------------------------------------

# 3. Product Category Calculation

A new field called:

``` text
product_category
```

is created from:

``` text
project_name
```

The project name is converted to lowercase and searched against a
keyword list.

The **first matching category wins**.

### Category rules

  -----------------------------------------------------------------------
  Category                            Example keywords
  ----------------------------------- -----------------------------------
  Cattle                              cattle, bull, calf, buffalo,
                                      qurbani, lamb

  Poultry                             poultry, duck, chicken, egg trade,
                                      sonali

  Fish                                fish, crab, tilapia, hilsha,
                                      pangas, shrimp, pabda

  Rice/Paddy                          rice, paddy, boro, aman

  Maize/Corn                          maize, corn

  Potato                              potato

  Onion                               onion

  Spices                              chilli, chili, turmeric, mustard

  Jute                                jute

  Fruit                               mango, watermelon, seasonal fruit

  Dairy                               dairy, cheese, molasses, honey,
                                      milk

  Goat                                goat

  Vegetable                           vegetable, tomato, cauliflower,
                                      cucumber, eggplant, okra, dherosh,
                                      pumpkin, garlic, kochu, taro

  Commodity Trade                     commodity

  Agri Input                          agricultural input, fertilizer,
                                      pesticide, micronutrient, seed
                                      import, agri machinery, silage,
                                      seed processing, seed

  Meat Processing                     meat processing
  -----------------------------------------------------------------------

If no keyword matches:

``` text
product_category = "Other"
```

------------------------------------------------------------------------

# 4. Investor-Level Calculations

The raw investment rows are grouped by:

``` text
customer_unique_id
```

Therefore, **one investor gets one row in the investor master table**.

------------------------------------------------------------------------

## 4.1 Total Invested

### Field

``` text
total_invested
```

### Calculated from

``` text
base_grand_total
```

### Formula

``` text
total_invested
= SUM(base_grand_total for the investor)
```

### Example

If an investor has:

  Investment     base_grand_total
  ------------ ------------------
  1                     Tk 40,000
  2                     Tk 80,000
  3                    Tk 100,000

Then:

``` text
total_invested = 40,000 + 80,000 + 100,000
               = Tk 220,000
```

------------------------------------------------------------------------

# 5. Investor Tier

### Field

``` text
tier
```

The tier is calculated from:

``` text
total_invested
```

### Rules

                   Total Invested Tier
  ------------------------------- ------
                    `< Tk 50,000` Low
       `Tk 50,000 – < Tk 250,000` Mid
    `Tk 250,000 – < Tk 2,000,000` High
                `>= Tk 2,000,000` VIP

### Formula

``` text
if total_invested < 50,000:
    Low

elif total_invested < 250,000:
    Mid

elif total_invested < 2,000,000:
    High

else:
    VIP
```

### Important

The tier is based on the investor's **combined investment amount**, not
the size of their latest investment.

------------------------------------------------------------------------

# 6. Number of Investments

### Field

``` text
num_investments
```

### Calculated from

``` text
id
```

### Formula

``` text
num_investments
= COUNT(id for the investor)
```

Each valid investment/order row counts as one investment.

### Example

If an investor has 5 valid rows:

``` text
num_investments = 5
```

------------------------------------------------------------------------

# 7. Average Investment

### Field

``` text
avg_investment
```

### Calculated from

``` text
base_grand_total
```

### Formula

``` text
avg_investment
= MEAN(base_grand_total for the investor)
```

### Example

Investments:

``` text
50,000
100,000
150,000
```

Then:

``` text
avg_investment
= (50,000 + 100,000 + 150,000) / 3
= Tk 100,000
```

------------------------------------------------------------------------

# 8. First Investment Date

### Field

``` text
first_investment
```

### Calculated from

``` text
invested_created_at
```

### Formula

``` text
first_investment
= MIN(invested_created_at for the investor)
```

This gives the earliest recorded investment date for that investor.

------------------------------------------------------------------------

# 9. Last Investment Date

### Field

``` text
last_investment
```

### Calculated from

``` text
invested_created_at
```

### Formula

``` text
last_investment
= MAX(invested_created_at for the investor)
```

This gives the most recent recorded investment date for that investor.

------------------------------------------------------------------------

# 10. Favorite Product Category

### Field

``` text
favorite_category
```

This is calculated from:

``` text
customer_unique_id
product_category
base_grand_total
```

First, the system calculates the investor's total investment in each
product category:

``` text
Category investment
= SUM(base_grand_total)
  grouped by investor + product_category
```

Then the category with the highest investment amount becomes the
favorite category.

### Example

An investor has:

  Category       Total Invested
  ------------ ----------------
  Cattle             Tk 300,000
  Fish               Tk 150,000
  Rice/Paddy         Tk 500,000

Therefore:

``` text
favorite_category = Rice/Paddy
```

### Important

"Favorite" means **the category where the investor has invested the most
money**, not necessarily the category they purchased most frequently.

------------------------------------------------------------------------

# 11. Last Project

### Field

``` text
last_project_name
```

### Calculated from

``` text
project_name
invested_created_at
```

The investment records are sorted by:

``` text
invested_created_at
```

Then the latest record for each investor is selected.

Therefore:

``` text
last_project_name
= project_name from the investor's latest investment
```

------------------------------------------------------------------------

# 12. Active Investment Flag

### Field

``` text
has_active_investment
```

The system checks the investor's investment statuses.

Running statuses are:

``` text
invested
disbursement_running
```

The formula is effectively:

``` text
has_active_investment = TRUE
if ANY investment has status:
    invested
    OR
    disbursement_running
```

Otherwise:

``` text
has_active_investment = FALSE
```

### Example

If an investor has:

  Investment   Status
  ------------ ----------
  1            closed
  2            closed
  3            invested

Then:

``` text
has_active_investment = TRUE
```

Because at least one investment is still in a running status.

------------------------------------------------------------------------

# 13. Preferred Tenure

### Field

``` text
preferred_tenure
```

This is calculated from:

``` text
tenure
```

For each investor, the system counts how many times each tenure appears.

### Example

An investor has:

``` text
6 months
12 months
12 months
12 months
24 months
24 months
```

Counts:

    Tenure   Count
  -------- -------
         6       1
        12       3
        24       2

Therefore:

``` text
preferred_tenure = 12 months
```

because it occurs most frequently.

### Tie rule

If two or more tenures have the same highest frequency, the system
chooses the **longest tenure**.

Example:

``` text
12 months → 2 investments
24 months → 2 investments
```

Then:

``` text
preferred_tenure = 24 months
```

------------------------------------------------------------------------

# 14. Days Since Last Investment

### Field

``` text
days_since_last_investment
```

### Calculated from

``` text
today
last_investment
```

### Formula

``` text
days_since_last_investment
= today - last_investment
```

The result is measured in days.

### Example

If:

``` text
Today = 30 Aug 2026
Last investment = 20 Aug 2026
```

Then:

``` text
days_since_last_investment = 10 days
```

This is recalculated using the current date whenever the application
runs.

------------------------------------------------------------------------

# 15. Activity Status

### Field

``` text
activity_status
```

This is calculated from:

``` text
days_since_last_investment
```

### Rules

    Days since last investment Activity Status
  ---------------------------- ----------------------
                  `<= 60 days` Active
                 `61–180 days` Cooling
                  `> 180 days` Inactive - Reach Out
                  Missing date Unknown

### Formula

``` text
if days_since_last_investment <= 60:
    Active

elif days_since_last_investment <= 180:
    Cooling

elif days_since_last_investment > 180:
    Inactive - Reach Out

if days_since_last_investment is missing:
    Unknown
```

------------------------------------------------------------------------

# 16. Product + Tenure Performance

The system also calculates overall performance for every combination of:

``` text
product_category + tenure
```

This is **not investor-level**. It is calculated across all valid
investment rows.

------------------------------------------------------------------------

## 16.1 Total Raised

### Field

``` text
total_raised
```

### Calculated from

``` text
base_grand_total
```

### Formula

``` text
total_raised
= SUM(base_grand_total)
grouped by product_category + tenure
```

Example:

  Product     Tenure   Investment
  --------- -------- ------------
  Cattle          12      100,000
  Cattle          12      200,000
  Cattle          12      150,000

Then:

``` text
Cattle + 12 months total_raised
= Tk 450,000
```

------------------------------------------------------------------------

# 17. Number of Investors per Product + Tenure

### Field

``` text
num_investors
```

### Calculated from

``` text
customer_unique_id
```

The system counts **unique investors**, not investment rows.

### Formula

``` text
num_investors
= COUNT(DISTINCT customer_unique_id)
grouped by product_category + tenure
```

### Example

If the Cattle + 12-month combination has:

``` text
Investor A → 2 investments
Investor B → 1 investment
Investor C → 3 investments
```

Then:

``` text
num_investors = 3
```

not 6.

------------------------------------------------------------------------

# 18. Average Investment per Product + Tenure

### Field

``` text
avg_investment
```

### Calculated from

``` text
base_grand_total
```

### Formula

``` text
avg_investment
= MEAN(base_grand_total)
grouped by product_category + tenure
```

This is the average investment transaction amount for that product +
tenure combination.

------------------------------------------------------------------------

# 19. Dashboard KPIs

The dashboard displays several summary numbers.

### Total Investors

``` text
Total investors = number of rows in final investor table
```

Because the final table contains one row per investor, this represents
the number of unique segmented investors.

### Total Invested

``` text
Total invested
= SUM(final.total_invested)
```

This is the total investment amount across all segmented investors.

### Tier Investor Counts

For each tier:

``` text
Low investors
Mid investors
High investors
VIP investors
```

the system counts the number of investors whose `tier` equals that tier.

------------------------------------------------------------------------

# 20. Investment by Product Category Chart

The chart groups valid investment rows by:

``` text
product_category
```

and calculates:

``` text
Total Invested
= SUM(base_grand_total)
```

Therefore, the chart answers:

> How much money has been invested in each product category?

------------------------------------------------------------------------

# 21. Investors by Preferred Tenure Chart

The chart uses:

``` text
preferred_tenure
```

from the final investor table.

It counts:

``` text
Number of investors per preferred tenure
```

It can optionally be filtered by investor tier.

For example:

``` text
VIP only
→ count VIP investors by preferred tenure
```

------------------------------------------------------------------------

# 22. Investor Activity Chart

The activity chart counts investors by:

``` text
activity_status
```

Possible groups:

-   Active
-   Cooling
-   Inactive - Reach Out
-   Unknown

------------------------------------------------------------------------

# 23. Master Table

The final investor master table combines all investor-level
calculations:

  -------------------------------------------------------------------------------------
  Field                          Calculated From                Calculation
  ------------------------------ ------------------------------ -----------------------
  `customer_unique_id`           Raw data                       Investor identifier

  `customer_name`                Raw data                       First name found for
                                                                investor

  `total_invested`               `base_grand_total`             Sum

  `num_investments`              `id`                           Count

  `avg_investment`               `base_grand_total`             Average

  `first_investment`             `invested_created_at`          Earliest date

  `last_investment`              `invested_created_at`          Latest date

  `tier`                         `total_invested`               Low / Mid / High / VIP

  `favorite_category`            `project_name` +               Category with highest
                                 `base_grand_total`             invested amount

  `last_project_name`            `project_name` +               Project from latest
                                 `invested_created_at`          investment

  `has_active_investment`        `status`                       TRUE if any running
                                                                investment exists

  `preferred_tenure`             `tenure`                       Most frequent tenure;
                                                                longest wins ties

  `days_since_last_investment`   `last_investment` + current    Date difference
                                 date                           

  `activity_status`              `days_since_last_investment`   Active / Cooling /
                                                                Inactive
  -------------------------------------------------------------------------------------

------------------------------------------------------------------------

# 24. Priority Outreach List

The PDF report creates a priority outreach list using:

``` text
tier ∈ {VIP, High}
AND
activity_status = "Inactive - Reach Out"
```

The displayed columns are:

-   Customer name
-   Tier
-   Total invested
-   Favorite category
-   Last project
-   Days since last investment

The list is limited to the first 30 matching investors.

This means the list is designed to identify:

> **High-value investors (High/VIP) who have not invested for more than
> 180 days.**

------------------------------------------------------------------------

# 25. Important Difference Between the Calculations

There are two different levels of analysis in this dashboard.

## Investor-level

These are calculated separately for each `customer_unique_id`:

-   Total invested
-   Number of investments
-   Average investment
-   First investment
-   Last investment
-   Tier
-   Favorite category
-   Last project
-   Active investment flag
-   Preferred tenure
-   Days since last investment
-   Activity status

## Overall product/tenure-level

These are calculated across all investors:

-   Total raised by product + tenure
-   Number of unique investors by product + tenure
-   Average investment by product + tenure

------------------------------------------------------------------------

# 26. Complete Calculation Flow

The complete logic can be understood as:

``` text
RAW ORDER EXPORT
       |
       v
Filter valid statuses
       |
       v
Convert date columns
       |
       v
Optional order date filter
       |
       v
Categorize project_name
       |
       v
VALID INVESTMENT DATA
       |
       +-----------------------------+
       |                             |
       v                             v
Investor-level grouping       Product + Tenure grouping
       |                             |
       v                             v
Total invested                 Total raised
Number of investments          Number of investors
Average investment             Average investment
First investment
Last investment
       |
       v
Assign investor tier
       |
       v
Favorite category
       |
       v
Last project
       |
       v
Active investment flag
       |
       v
Preferred tenure
       |
       v
Days since last investment
       |
       v
Activity status
       |
       v
FINAL INVESTOR MASTER TABLE
       |
       +--> Dashboard KPIs
       +--> Charts
       +--> Filters
       +--> CSV export
       +--> Priority outreach PDF
```

------------------------------------------------------------------------

# 27. Quick Reference: "Calculated From What?"

  ------------------------------------------------------------------------------
  Output                  Source field(s)                Method
  ----------------------- ------------------------------ -----------------------
  Product category        `project_name`                 Keyword matching

  Total invested          `base_grand_total`             SUM per investor

  Number of investments   `id`                           COUNT per investor

  Average investment      `base_grand_total`             MEAN per investor

  First investment        `invested_created_at`          MIN

  Last investment         `invested_created_at`          MAX

  Tier                    `total_invested`               Threshold rules

  Favorite category       `product_category`,            Highest category
                          `base_grand_total`             investment

  Last project            `project_name`,                Project from latest
                          `invested_created_at`          investment

  Active investment       `status`                       Any running status

  Preferred tenure        `tenure`                       Most frequent; longest
                                                         wins tie

  Days since last         `last_investment`, current     Date difference
  investment              date                           

  Activity status         `days_since_last_investment`   60/180-day rules

  Product + tenure total  `product_category`, `tenure`,  SUM
  raised                  `base_grand_total`             

  Product + tenure        `product_category`, `tenure`,  Unique COUNT
  investors               `customer_unique_id`           

  Product + tenure        `product_category`, `tenure`,  MEAN
  average                 `base_grand_total`             
  ------------------------------------------------------------------------------

------------------------------------------------------------------------

## Source

This README is based on the calculation logic implemented in the
provided **WeGro Investor Segmentation** Python/Streamlit code.
