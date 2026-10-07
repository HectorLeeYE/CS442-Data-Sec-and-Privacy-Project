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
