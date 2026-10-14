"""Singapore-flavoured vocabularies shared by the corpus generator and the redactor.

Detector lexicons are deliberately NOT these lists verbatim: see detect.py, where
some generator values are absent from the lexicons so E1 measures a real miss rate.
"""

SURNAMES = ["Tan", "Lim", "Lee", "Ng", "Ong", "Wong", "Goh", "Chua", "Chan", "Koh",
            "Teo", "Ang", "Yeo", "Tay", "Ho", "Low", "Sim", "Chong", "Kumar", "Pillai",
            "Nair", "Singh", "Rahman", "Ismail", "Hassan", "Abdullah", "Fernandez", "Menon"]
GIVEN_CHINESE = ["Wei Ming", "Jia Hui", "Hui Min", "Jun Jie", "Xin Yi", "Kai Wen", "Mei Ling",
                 "Zhi Hao", "Shu Fen", "Boon Keng", "Siew Lan", "Yong Sheng"]
GIVEN_MALAY = ["Nurul", "Aisyah", "Farhan", "Hafiz", "Siti", "Amirul", "Zul", "Fatimah"]
GIVEN_INDIAN = ["Priya", "Arjun", "Kavitha", "Rajesh", "Deepa", "Suresh", "Anand", "Lakshmi"]
GIVEN = GIVEN_CHINESE + GIVEN_MALAY + GIVEN_INDIAN

AGENTS = ["Priya Nair", "Daniel Koh", "Siti Rahman", "Marcus Teo"]

# town -> region (the GREEN-tier generalization of a LOCATION)
TOWNS = {
    "Tampines": "the East", "Bedok": "the East", "Pasir Ris": "the East",
    "Jurong": "the West", "Clementi": "the West", "Bukit Batok": "the West",
    "Woodlands": "the North", "Yishun": "the North", "Sembawang": "the North",
    "Ang Mo Kio": "the North-East", "Hougang": "the North-East", "Punggol": "the North-East",
    "Serangoon": "the North-East", "Toa Payoh": "Central", "Bishan": "Central",
    "Queenstown": "Central", "Novena": "Central", "Raffles Place": "Central",
    "Holland Village": "Central", "Kallang": "Central",
}
STREET_KINDS = ["Street", "Avenue", "Road", "Drive", "Crescent"]

# employer -> sector (generalization)
EMPLOYERS = {
    "Changi Airport Group": "an aviation company", "Singtel": "a telco", "Grab": "a tech company",
    "Shopee": "a tech company", "Keppel": "an engineering firm", "Sembcorp": "an engineering firm",
    "National University Hospital": "a hospital", "Tan Tock Seng Hospital": "a hospital",
    "Ministry of Education": "the civil service", "PSA International": "a logistics company",
    "Wilmar": "a trading company", "Raffles Medical": "a healthcare company",
    "Mediacorp": "a media company", "Jurong Port": "a logistics company", "CapitaLand": "a property company",
}
# occupation -> sector
OCCUPATIONS = {
    "teacher": "an educator", "nurse": "a healthcare worker", "doctor": "a healthcare worker",
    "engineer": "an engineer", "software developer": "a tech worker", "accountant": "a finance professional",
    "lawyer": "a legal professional", "taxi driver": "a transport worker", "hawker": "a business owner",
    "property agent": "a sales professional", "pilot": "a transport worker", "civil servant": "a public officer",
    "pharmacist": "a healthcare worker", "contractor": "a business owner", "financial advisor": "a finance professional",
}
NATIONALITIES = ["Singaporean", "Malaysian", "Indonesian", "Indian", "Chinese", "Filipino",
                 "Vietnamese", "Thai", "Australian", "British"]
HEALTH = ["chemotherapy", "kidney dialysis", "heart surgery", "cancer treatment", "a stroke",
          "diabetes treatment", "knee replacement", "IVF treatment"]
LEGAL = ["divorce", "custody case", "bankruptcy proceedings", "lawsuit", "court case", "probate dispute"]
PETS = ["Lucky", "Coco", "Mochi", "Kopi", "Milo", "Bobo", "Lucy", "Max"]
BANKS = ["Merlion Bank", "Lion City Bank", "Straits Bank"]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com.sg", "hotmail.com", "singnet.com.sg", "outlook.com"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

# Surrogate names share no token with the real-name vocabulary, so a surrogate can never
# reproduce part of the real name or collide with another real client (a false linkage).
SURROGATE_SURNAMES = ["Quek", "Seah", "Toh", "Lau", "Heng", "Foo", "Yap", "Kwek", "Pang", "Soh", "Tham",
                      "Wee", "Iyer", "Rao", "Das", "Osman", "Yusof", "Salleh", "Aziz", "Pereira", "Danker"]
SURROGATE_GIVEN = ["Li Ting", "Pei Shan", "Zi Han", "Zhen Yu", "Qiu Yan", "Si Qi", "Rui En", "Kok Leong",
                   "Nadia", "Iskandar", "Hidayah", "Ridzuan", "Meena", "Vikram", "Shalini", "Gopal"]

# Added in round 2 (A6): types the plan listed but the first version never generated.
RELIGIONS = ["Buddhist", "Christian", "Muslim", "Hindu", "Taoist", "Catholic", "Sikh"]
PEP_ROLES = ["a member of parliament", "a minister", "an ambassador", "a senior civil servant",
             "a judge", "a grassroots leader"]
RELATIONS = ["mother", "father", "wife", "husband", "son", "daughter", "brother", "sister"]
# SWIFT/BIC -> whether the bank is local (the GREEN generalization of a SWIFT code)
SWIFT_CODES = ["DBSSSGSG", "OCBCSGSG", "UOVBSGSG", "HSBCGB2L", "DEUTDEFF", "BNPAFRPP", "CITIUS33", "MBBEMYKL"]
IBAN_BANKS = ["NWBK", "BARC", "LOYD", "MIDL"]          # GB IBANs carry a 4-letter bank code

# Spoken digits in the other languages of a Singapore call (A7): Mandarin pinyin, Malay.
PINYIN_DIGITS = ["ling", "yi", "er", "san", "si", "wu", "liu", "qi", "ba", "jiu"]
MALAY_DIGITS = ["kosong", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "lapan", "sembilan"]
# What ASR writes for a digit it mishears as a common word.
HOMOPHONES = {"four": "for", "two": "to", "eight": "ate", "one": "won"}

# Detector-only gazetteers (round 3, item 2.4): written from public knowledge of Singapore, not from
# the generator or the held-out calls. Common English words ("Grab", "Pioneer") are left out because
# they would redact ordinary speech.
SG_EMPLOYERS = [
    "Singapore Airlines", "Scoot", "SATS", "Changi Airport Group", "SBS Transit", "SMRT", "ComfortDelGro", "Gojek",
    "Singtel", "StarHub", "Shopee", "Lazada", "Razer", "Keppel", "Sembcorp", "ST Engineering", "Seatrium",
    "PSA International", "Jurong Port", "CapitaLand", "City Developments", "Mediacorp", "SPH Media", "Wilmar", "Olam",
    "Temasek", "GIC", "NTUC FairPrice", "FairPrice", "Sheng Siong", "Cold Storage", "Raffles Medical", "Parkway",
    "Changi General Hospital", "Singapore General Hospital", "Tan Tock Seng Hospital", "National University Hospital",
    "Khoo Teck Puat Hospital", "Ng Teng Fong General Hospital", "Sengkang General Hospital", "KK Hospital",
    "KK Women's and Children's Hospital", "Mount Elizabeth Hospital", "Gleneagles Hospital", "Mount Alvernia Hospital",
    "Institute of Mental Health", "National University of Singapore", "Nanyang Technological University",
    "Singapore Management University", "Ministry of Education", "Ministry of Health", "Ministry of Manpower",
    "Housing and Development Board", "CPF Board", "IRAS", "Singapore Police Force", "SCDF",
]
# Planning areas and neighbourhoods missing from TOWNS -> region (the GREEN generalization).
SG_PLACES = {
    "Bukit Timah": "Central", "Bukit Merah": "Central", "Tanjong Pagar": "Central", "Outram": "Central",
    "Chinatown": "Central", "Orchard": "Central", "River Valley": "Central", "Tiong Bahru": "Central",
    "Redhill": "Central", "Telok Blangah": "Central", "Buona Vista": "Central", "Thomson": "Central",
    "Potong Pasir": "Central", "MacPherson": "Central", "Little India": "Central", "Bugis": "Central",
    "Marine Parade": "the East", "Geylang": "the East", "Paya Lebar": "the East", "Katong": "the East",
    "Joo Chiat": "the East", "Siglap": "the East", "Kembangan": "the East", "Eunos": "the East", "Simei": "the East",
    "Changi": "the East", "Aljunied": "the East",
    "Bukit Panjang": "the West", "Choa Chu Kang": "the West", "Tuas": "the West", "Boon Lay": "the West",
    "Jurong East": "the West", "Jurong West": "the West", "Tengah": "the West", "Pasir Panjang": "the West",
    "Kent Ridge": "the West", "West Coast": "the West",
    "Admiralty": "the North", "Kranji": "the North", "Yew Tee": "the North", "Marsiling": "the North",
    "Canberra": "the North", "Mandai": "the North",
    "Sengkang": "the North-East", "Seletar": "the North-East", "Lorong Chuan": "the North-East",
}
# Destinations that make a transfer an overseas one (triage). Countries and cities, not nationalities.
FOREIGN_PLACES = [
    "Malaysia", "Johor", "Kuala Lumpur", "Indonesia", "Jakarta", "Batam", "Thailand", "Bangkok", "Vietnam",
    "Philippines", "Manila", "India", "Chennai", "Mumbai", "Delhi", "China", "Shanghai", "Beijing", "Shenzhen",
    "Hong Kong", "Taiwan", "Japan", "Tokyo", "Korea", "Seoul", "Australia", "Sydney", "Melbourne", "New Zealand",
    "United Kingdom", "UK", "London", "Germany", "France", "Switzerland", "Dubai", "United States", "USA", "America",
    "New York", "Canada", "Cambodia", "Myanmar", "Bangladesh", "Sri Lanka", "Pakistan", "Nepal",
]

# Round 4: words of real conversation that NER takes for names. Written from language knowledge, not from the
# NSC transcripts: English fillers and discourse words, Singlish particles, common Malay function words, common
# Mandarin pinyin function syllables, and kinship / generic person nouns. A name-like span made only of these
# (or of English stop words) is dropped, and none of them is ever propagated.
FUNCTION_WORDS = set("""
mm mmm hmm hm err erm uh um ah eh oh ooh aiya okay ok ya yah yeah yup yep nope like right so well
lah leh lor orh hor sia meh hais wah alamak aiyo aiyah ma
tak ada dia aku kau nak yang punya macam bila kan lagi sudah dah pun jer kat dengan untuk ini itu tu ni apa
saya kita lepas
wo ni ta de le ma ne shi bu you zai
mum mom mummy mother dad daddy father daughter son wife husband friend friends boss law sister brother
""".split())
