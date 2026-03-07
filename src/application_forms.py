# Sample application forms for testing
# Loan types reference data/workspace/loan_policy_documents
# Mix of applications likely to PASS and FAIL eligibility criteria

steve_application_str = """Applicant Name: Steven Goodman
What loan are you applying for: asset finance
What is the purpose of this loan?: Purchase IT equipment
How much would you like to borrow?: £10000
Over what term (# months)?: 24

Is your company registered with Companies House?: Yes

Company Name: Goodmans Consulting

What is your industry?: Business Support Services

When did you start trading?: 11/07/2012

What is your typical annual turnover?: £100000

Last 12 months profit: £84000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £0

Monthly expense amount, Not including mortgage or rent repayments: £1500

How much is your monthly rent or mortgage payment?: £3000

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 200

How much non-business income do you receive each month?: 0

Monthly other household income: 5000


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Steve  
    Surname: Goodman
    Percentage of control: 25%
    Year of Birth: 1973
    Mobile phone number: 012345678
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Unknown"""


synthesia_application_str = """Applicant Name: Steffen Tjerrild-Hansen
What loan are you applying for: debt-financing
What is the purpose of this loan?: servicing debt
How much would you like to borrow?: £1,000,0000
Over what term (# months)?: 12

Is your company registered with Companies House?: Yes

Company Name: Synthesia 

What is your industry?: Business Support Services

When did you start trading?: 11/07/2012

What is your typical annual turnover?: £58,000,000

Last 12 months profit: £-10,000,000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £0

Monthly expense amount, Not including mortgage or rent repayments: £1500

How much is your monthly rent or mortgage payment?: £3000

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 200

How much non-business income do you receive each month?: 0

Monthly other household income: 5000


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Michael 
    Surname: T
    Percentage of control: 25%
    Year of Birth: 1990
    Mobile phone number: 012345678
    What is the director's residential status?: Owner With Mortgage
    Residential Address: London"""


# Likely PASS: Profitable, established, invoice finance with substantial invoices
maria_invoice_application_str = """Applicant Name: Maria Kowalski
What loan are you applying for: invoice-finance
What is the purpose of this loan?: Unlock cash tied in unpaid invoices
How much would you like to borrow?: £85000
Over what term (# months)?: 12

Is your company registered with Companies House?: Yes

Company Name: Kowalski Logistics Ltd

What is your industry?: Logistics

When did you start trading?: 03/09/2018

What is your typical annual turnover?: £420000

Last 12 months profit: £62000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £95000

Monthly expense amount, Not including mortgage or rent repayments: £2200

How much is your monthly rent or mortgage payment?: £1800

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 450

How much non-business income do you receive each month?: 0

Monthly other household income: 3200


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Maria
    Surname: Kowalski
    Percentage of control: 100%
    Year of Birth: 1985
    Mobile phone number: 07700987654
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Birmingham"""


# Likely FAIL: Invoice finance with no invoices
peter_no_invoices_application_str = """Applicant Name: Peter Chen
What loan are you applying for: invoice-finance
What is the purpose of this loan?: Working capital
How much would you like to borrow?: £50000
Over what term (# months)?: 6

Is your company registered with Companies House?: Yes

Company Name: Chen Retail Solutions

What is your industry?: Retail

When did you start trading?: 15/04/2020

What is your typical annual turnover?: £180000

Last 12 months profit: £12000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £0

Monthly expense amount, Not including mortgage or rent repayments: £3500

How much is your monthly rent or mortgage payment?: £2200

How many dependants do you have?: 0

How much do you typically spend on childcare expenses per month?: 0

How much non-business income do you receive each month?: 0

Monthly other household income: 0


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Peter
    Surname: Chen
    Percentage of control: 100%
    Year of Birth: 1982
    Mobile phone number: 07890123456
    What is the director's residential status?: Renting
    Residential Address: Manchester"""


# Likely PASS: Merchant cash advance with card payments
sarah_mca_application_str = """Applicant Name: Sarah Mitchell
What loan are you applying for: merchant-cash-advance
What is the purpose of this loan?: Seasonal stock purchase
How much would you like to borrow?: £25000
Over what term (# months)?: 9

Is your company registered with Companies House?: Yes

Company Name: Mitchell Coffee Roasters Ltd

What is your industry?: Food and Beverage

When did you start trading?: 22/01/2019

What is your typical annual turnover?: £310000

Last 12 months profit: £45000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £8000

Monthly expense amount, Not including mortgage or rent repayments: £4200

How much is your monthly rent or mortgage payment?: £2800

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 350

How much non-business income do you receive each month?: 0

Monthly other household income: 4100


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Sarah
    Surname: Mitchell
    Percentage of control: 75%
    Year of Birth: 1978
    Mobile phone number: 07456123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Edinburgh"""


# Likely FAIL: Merchant cash advance but no card payments
james_no_cards_application_str = """Applicant Name: James O'Brien
What loan are you applying for: merchant-cash-advance
What is the purpose of this loan?: Equipment upgrade
How much would you like to borrow?: £35000
Over what term (# months)?: 12

Is your company registered with Companies House?: Yes

Company Name: O'Brien Wholesale Ltd

What is your industry?: Wholesale

When did you start trading?: 08/11/2016

What is your typical annual turnover?: £890000

Last 12 months profit: £78000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £125000

Monthly expense amount, Not including mortgage or rent repayments: £5100

How much is your monthly rent or mortgage payment?: £1900

How many dependants do you have?: 3

How much do you typically spend on childcare expenses per month?: 800

How much non-business income do you receive each month?: 0

Monthly other household income: 5500


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: James
    Surname: O'Brien
    Percentage of control: 50%
    Year of Birth: 1975
    Mobile phone number: 07987654321
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Leeds"""


# Likely PASS: Working capital, strong profile
emma_working_capital_application_str = """Applicant Name: Emma Watson
What loan are you applying for: working-capital-finance
What is the purpose of this loan?: Pay suppliers and meet payroll
How much would you like to borrow?: £45000
Over what term (# months)?: 18

Is your company registered with Companies House?: Yes

Company Name: Watson Design Studio Ltd

What is your industry?: Creative Services

When did you start trading?: 12/06/2015

What is your typical annual turnover?: £285000

Last 12 months profit: £52000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £42000

Monthly expense amount, Not including mortgage or rent repayments: £3800

How much is your monthly rent or mortgage payment?: £2400

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 600

How much non-business income do you receive each month?: 0

Monthly other household income: 3800


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Emma
    Surname: Watson
    Percentage of control: 100%
    Year of Birth: 1988
    Mobile phone number: 07770123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Bristol"""


# Likely FAIL: Expecting income decrease
david_declining_application_str = """Applicant Name: David Patel
What loan are you applying for: business-loans
What is the purpose of this loan?: Refinance existing debt
How much would you like to borrow?: £75000
Over what term (# months)?: 36

Is your company registered with Companies House?: Yes

Company Name: Patel Electronics Ltd

What is your industry?: Retail

When did you start trading?: 20/03/2017

What is your typical annual turnover?: £520000

Last 12 months profit: £18000

Do you expect your income to decrease in the next 12 months?: Yes

Do you accept card payments?: Yes

How much is owed to you in invoices?: £15000

Monthly expense amount, Not including mortgage or rent repayments: £4500

How much is your monthly rent or mortgage payment?: £2600

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 500

How much non-business income do you receive each month?: 0

Monthly other household income: 4200


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: David
    Surname: Patel
    Percentage of control: 100%
    Year of Birth: 1980
    Mobile phone number: 07555123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Leicester"""


# Likely PASS: Bridging loan for property
fiona_bridging_application_str = """Applicant Name: Fiona Scott
What loan are you applying for: bridging-loans
What is the purpose of this loan?: Bridge between property sale and purchase
How much would you like to borrow?: £280000
Over what term (# months)?: 6

Is your company registered with Companies House?: Yes

Company Name: Scott Property Holdings Ltd

What is your industry?: Property

When did you start trading?: 05/08/2014

What is your typical annual turnover?: £720000

Last 12 months profit: £95000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £0

Monthly expense amount, Not including mortgage or rent repayments: £2800

How much is your monthly rent or mortgage payment?: £4500

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 250

How much non-business income do you receive each month?: 0

Monthly other household income: 6000


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Fiona
    Surname: Scott
    Percentage of control: 60%
    Year of Birth: 1972
    Mobile phone number: 07888123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Surrey"""


# Likely PASS: Property development finance
oliver_property_dev_application_str = """Applicant Name: Oliver Wright
What loan are you applying for: property-development-finance
What is the purpose of this loan?: Refurbish commercial premises
How much would you like to borrow?: £425000
Over what term (# months)?: 18

Is your company registered with Companies House?: Yes

Company Name: Wright Development Ltd

What is your industry?: Construction

When did you start trading?: 10/02/2013

What is your typical annual turnover?: £1850000

Last 12 months profit: £165000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £220000

Monthly expense amount, Not including mortgage or rent repayments: £6200

How much is your monthly rent or mortgage payment?: £3200

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 400

How much non-business income do you receive each month?: 0

Monthly other household income: 5200


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Oliver
    Surname: Wright
    Percentage of control: 100%
    Year of Birth: 1970
    Mobile phone number: 07666123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Kent"""


# Likely FAIL: Very new business, large loan request
rachel_startup_application_str = """Applicant Name: Rachel Green
What loan are you applying for: unsecured-business-loans
What is the purpose of this loan?: Initial capital for launch
How much would you like to borrow?: £120000
Over what term (# months)?: 48

Is your company registered with Companies House?: Yes

Company Name: Green Innovations Ltd

What is your industry?: Technology

When did you start trading?: 15/09/2024

What is your typical annual turnover?: £45000

Last 12 months profit: £-8000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £12000

Monthly expense amount, Not including mortgage or rent repayments: £3200

How much is your monthly rent or mortgage payment?: £1800

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 300

How much non-business income do you receive each month?: 2000

Monthly other household income: 3500


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Rachel
    Surname: Green
    Percentage of control: 100%
    Year of Birth: 1992
    Mobile phone number: 07333123456
    What is the director's residential status?: Renting
    Residential Address: Cambridge"""


# Likely PASS: Revolving credit facility, established business
andrew_revolving_application_str = """Applicant Name: Andrew Hughes
What loan are you applying for: revolving-credit-facility
What is the purpose of this loan?: Flexible working capital
How much would you like to borrow?: £75000
Over what term (# months)?: 24

Is your company registered with Companies House?: Yes

Company Name: Hughes Manufacturing Ltd

What is your industry?: Manufacturing

When did you start trading?: 01/04/2011

What is your typical annual turnover?: £1250000

Last 12 months profit: £142000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £185000

Monthly expense amount, Not including mortgage or rent repayments: £5500

How much is your monthly rent or mortgage payment?: £4100

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 550

How much non-business income do you receive each month?: 0

Monthly other household income: 4800


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Andrew
    Surname: Hughes
    Percentage of control: 55%
    Year of Birth: 1968
    Mobile phone number: 07999123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Sheffield"""


# Likely FAIL: Sole trader, unregistered, large secured-style request
kate_sole_trader_application_str = """Applicant Name: Kate Thompson
What loan are you applying for: secured-business-loans
What is the purpose of this loan?: Buy commercial vehicle
How much would you like to borrow?: £65000
Over what term (# months)?: 36

Is your company registered with Companies House?: No

Company Name: Kate Thompson Plumbing

What is your industry?: Construction

When did you start trading?: 18/07/2019

What is your typical annual turnover?: £95000

Last 12 months profit: £22000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £8000

Monthly expense amount, Not including mortgage or rent repayments: £1800

How much is your monthly rent or mortgage payment?: £1200

How many dependants do you have?: 0

How much do you typically spend on childcare expenses per month?: 0

How much non-business income do you receive each month?: 0

Monthly other household income: 0


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Kate
    Surname: Thompson
    Percentage of control: 100%
    Year of Birth: 1987
    Mobile phone number: 07777123456
    What is the director's residential status?: Renting
    Residential Address: Nottingham"""


# Likely PASS: Short-term business loan, solid numbers
michael_short_term_application_str = """Applicant Name: Michael Okonkwo
What loan are you applying for: short-term-business-loans
What is the purpose of this loan?: Tax bill in instalments
How much would you like to borrow?: £15000
Over what term (# months)?: 6

Is your company registered with Companies House?: Yes

Company Name: Okonkwo Consulting Ltd

What is your industry?: Business Support Services

When did you start trading?: 22/11/2018

What is your typical annual turnover?: £195000

Last 12 months profit: £38000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £28000

Monthly expense amount, Not including mortgage or rent repayments: £2400

How much is your monthly rent or mortgage payment?: £1500

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 280

How much non-business income do you receive each month?: 0

Monthly other household income: 2900


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Michael
    Surname: Okonkwo
    Percentage of control: 100%
    Year of Birth: 1984
    Mobile phone number: 07444123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Cardiff"""


# Likely FAIL: Large loss, debt refinancing
sophie_loss_application_str = """Applicant Name: Sophie Laurent
What loan are you applying for: debt-financing
What is the purpose of this loan?: Refinance existing loans
How much would you like to borrow?: £200000
Over what term (# months)?: 24

Is your company registered with Companies House?: Yes

Company Name: Laurent Catering Ltd

What is your industry?: Hospitality

When did you start trading?: 14/05/2020

What is your typical annual turnover?: £340000

Last 12 months profit: £-45000

Do you expect your income to decrease in the next 12 months?: Yes

Do you accept card payments?: Yes

How much is owed to you in invoices?: £12000

Monthly expense amount, Not including mortgage or rent repayments: £4800

How much is your monthly rent or mortgage payment?: £3800

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 700

How much non-business income do you receive each month?: 0

Monthly other household income: 2100


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Sophie
    Surname: Laurent
    Percentage of control: 100%
    Year of Birth: 1986
    Mobile phone number: 07888123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: London"""


# Likely PASS: Construction finance, established
thomas_construction_application_str = """Applicant Name: Thomas Byrne
What loan are you applying for: construction-finance
What is the purpose of this loan?: Building materials for ongoing project
How much would you like to borrow?: £165000
Over what term (# months)?: 12

Is your company registered with Companies House?: Yes

Company Name: Byrne Builders Ltd

What is your industry?: Construction

When did you start trading?: 09/12/2012

What is your typical annual turnover?: £680000

Last 12 months profit: £72000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £95000

Monthly expense amount, Not including mortgage or rent repayments: £4200

How much is your monthly rent or mortgage payment?: £1900

How many dependants do you have?: 3

How much do you typically spend on childcare expenses per month?: 650

How much non-business income do you receive each month?: 0

Monthly other household income: 5100


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Thomas
    Surname: Byrne
    Percentage of control: 70%
    Year of Birth: 1976
    Mobile phone number: 07555123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Dublin"""


# Likely PASS: Commercial property finance
victoria_commercial_property_application_str = """Applicant Name: Victoria Singh
What loan are you applying for: commercial-property-finance
What is the purpose of this loan?: Purchase warehouse premises
How much would you like to borrow?: £620000
Over what term (# months)?: 240

Is your company registered with Companies House?: Yes

Company Name: Singh Distribution Ltd

What is your industry?: Wholesale

When did you start trading?: 07/03/2010

What is your typical annual turnover?: £2100000

Last 12 months profit: £198000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £310000

Monthly expense amount, Not including mortgage or rent repayments: £7200

How much is your monthly rent or mortgage payment?: £5500

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 420

How much non-business income do you receive each month?: 0

Monthly other household income: 6100


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Victoria
    Surname: Singh
    Percentage of control: 60%
    Year of Birth: 1974
    Mobile phone number: 07666123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Birmingham"""


# Likely FAIL: Trade finance with insufficient turnover/history
william_trade_application_str = """Applicant Name: William Foster
What loan are you applying for: trade-finance
What is the purpose of this loan?: Import stock from overseas
How much would you like to borrow?: £350000
Over what term (# months)?: 6

Is your company registered with Companies House?: Yes

Company Name: Foster Imports Ltd

What is your industry?: Retail

When did you start trading?: 01/06/2023

What is your typical annual turnover?: £125000

Last 12 months profit: £15000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £18000

Monthly expense amount, Not including mortgage or rent repayments: £2800

How much is your monthly rent or mortgage payment?: £1400

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 200

How much non-business income do you receive each month?: 0

Monthly other household income: 2600


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: William
    Surname: Foster
    Percentage of control: 100%
    Year of Birth: 1991
    Mobile phone number: 07999123456
    What is the director's residential status?: Renting
    Residential Address: Liverpool"""


# Likely PASS: Invoice discounting, B2B with invoices
jennifer_invoice_discounting_application_str = """Applicant Name: Jennifer Walsh
What loan are you applying for: invoice-discounting
What is the purpose of this loan?: Unlock cash flow from B2B invoices
How much would you like to borrow?: £120000
Over what term (# months)?: 12

Is your company registered with Companies House?: Yes

Company Name: Walsh Recruitment Ltd

What is your industry?: Recruitment

When did you start trading?: 18/09/2016

What is your typical annual turnover?: £890000

Last 12 months profit: £78000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £165000

Monthly expense amount, Not including mortgage or rent repayments: £5100

How much is your monthly rent or mortgage payment?: £2700

How many dependants do you have?: 2

How much do you typically spend on childcare expenses per month?: 480

How much non-business income do you receive each month?: 0

Monthly other household income: 4500


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Jennifer
    Surname: Walsh
    Percentage of control: 85%
    Year of Birth: 1982
    Mobile phone number: 07777123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Glasgow"""


# Likely PASS: Invoice factoring, manufacturing with invoices
robert_invoice_factoring_application_str = """Applicant Name: Robert Martinez
What loan are you applying for: invoice-factoring
What is the purpose of this loan?: Fund raw material purchases
How much would you like to borrow?: £95000
Over what term (# months)?: 12

Is your company registered with Companies House?: Yes

Company Name: Martinez Components Ltd

What is your industry?: Manufacturing

When did you start trading?: 25/02/2014

What is your typical annual turnover?: £520000

Last 12 months profit: £58000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: No

How much is owed to you in invoices?: £148000

Monthly expense amount, Not including mortgage or rent repayments: £3800

How much is your monthly rent or mortgage payment?: £2400

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 320

How much non-business income do you receive each month?: 0

Monthly other household income: 3900


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Robert
    Surname: Martinez
    Percentage of control: 100%
    Year of Birth: 1979
    Mobile phone number: 07444123456
    What is the director's residential status?: Owner With Mortgage
    Residential Address: Wolverhampton"""


# Likely FAIL: Loan amount far exceeds turnover for unsecured
alexandra_overreach_application_str = """Applicant Name: Alexandra Park
What loan are you applying for: unsecured-business-loans
What is the purpose of this loan?: Expansion into new markets
How much would you like to borrow?: £800000
Over what term (# months)?: 60

Is your company registered with Companies House?: Yes

Company Name: Park Digital Agency Ltd

What is your industry?: Business Support Services

When did you start trading?: 04/08/2021

What is your typical annual turnover?: £165000

Last 12 months profit: £24000

Do you expect your income to decrease in the next 12 months?: No

Do you accept card payments?: Yes

How much is owed to you in invoices?: £42000

Monthly expense amount, Not including mortgage or rent repayments: £2900

How much is your monthly rent or mortgage payment?: £2100

How many dependants do you have?: 1

How much do you typically spend on childcare expenses per month?: 400

How much non-business income do you receive each month?: 0

Monthly other household income: 3700


Provide information of all directors or beneficial owners controlling more than 25% of the company:

Person 1:
    First name: Alexandra
    Surname: Park
    Percentage of control: 100%
    Year of Birth: 1989
    Mobile phone number: 07333123456
    What is the director's residential status?: Renting
    Residential Address: Brighton"""


# Expected eligibility outcome (PASS/FAIL) per application — matches comment above each declaration
APPLICATION_EXPECTED_OUTCOMES = {
    "steve_application_str": "PASS",
    "synthesia_application_str": "FAIL",
    "maria_invoice_application_str": "PASS",
    "peter_no_invoices_application_str": "FAIL",
    "sarah_mca_application_str": "PASS",
    "james_no_cards_application_str": "FAIL",
    "emma_working_capital_application_str": "PASS",
    "david_declining_application_str": "FAIL",
    "fiona_bridging_application_str": "PASS",
    "oliver_property_dev_application_str": "PASS",
    "rachel_startup_application_str": "FAIL",
    "andrew_revolving_application_str": "PASS",
    "kate_sole_trader_application_str": "FAIL",
    "michael_short_term_application_str": "PASS",
    "sophie_loss_application_str": "FAIL",
    "thomas_construction_application_str": "PASS",
    "victoria_commercial_property_application_str": "PASS",
    "william_trade_application_str": "FAIL",
    "jennifer_invoice_discounting_application_str": "PASS",
    "robert_invoice_factoring_application_str": "PASS",
    "alexandra_overreach_application_str": "FAIL",
}


def get_applications():
    """Return a dict of application name -> {content, expected_outcome} for all *_application_str vars."""
    import sys
    mod = sys.modules[__name__]
    return {
        name: {
            "content": getattr(mod, name),
            "expected_outcome": APPLICATION_EXPECTED_OUTCOMES.get(name),
        }
        for name in APPLICATION_EXPECTED_OUTCOMES
    }
