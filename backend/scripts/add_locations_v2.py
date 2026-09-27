"""
One-off data migration: extend the monitored set so every state and union
territory has at least one location, and add the dated flood events that belong
to the new locations.

Idempotent - rows whose id already exists are skipped. After running it:

    python backend/scripts/enrich_locations.py --missing-only
    (then restart the backend; climatology for new locations builds on boot)

Populations are Census of India 2011 city / town figures. Events are included
only where the date and place are well documented; where the peak day is
uncertain the row says date_precision "month".
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "app" / "data"

# id, name, name_hi, state, district, lat, lon, population, basin, river, coastal, cwc_basin
NEW = [
    # Madhya Pradesh
    ("bhopal", "Bhopal", "भोपाल", "Madhya Pradesh", "Bhopal", 23.2599, 77.4126, 1798218, "Betwa", "Kaliasot", False, "Ganga"),
    ("indore", "Indore", "इंदौर", "Madhya Pradesh", "Indore", 22.7196, 75.8577, 1964086, "Chambal", "Khan", False, "Ganga"),
    ("jabalpur", "Jabalpur", "जबलपुर", "Madhya Pradesh", "Jabalpur", 23.1815, 79.9864, 1055525, "Narmada", "Narmada", False, "Narmada"),
    ("narmadapuram", "Narmadapuram", "नर्मदापुरम", "Madhya Pradesh", "Narmadapuram", 22.7519, 77.7289, 117988, "Narmada", "Narmada", False, "Narmada"),
    ("gwalior", "Gwalior", "ग्वालियर", "Madhya Pradesh", "Gwalior", 26.2183, 78.1828, 1069276, "Chambal", "Sindh", False, "Ganga"),
    # Rajasthan
    ("jaipur", "Jaipur", "जयपुर", "Rajasthan", "Jaipur", 26.9124, 75.7873, 3046163, "Banas", "Dravyavati", False, "Ganga"),
    ("kota", "Kota", "कोटा", "Rajasthan", "Kota", 25.2138, 75.8648, 1001694, "Chambal", "Chambal", False, "Ganga"),
    ("ajmer", "Ajmer", "अजमेर", "Rajasthan", "Ajmer", 26.4499, 74.6399, 542321, "Luni", "Sagarmati", False, "West Flowing Rivers"),
    ("barmer", "Barmer", "बाड़मेर", "Rajasthan", "Barmer", 25.7532, 71.4181, 100367, "Luni", "Luni", False, "West Flowing Rivers"),
    # Chhattisgarh
    ("raipur", "Raipur", "रायपुर", "Chhattisgarh", "Raipur", 21.2514, 81.6296, 1010087, "Mahanadi", "Kharun", False, "Mahanadi"),
    ("bilaspur_cg", "Bilaspur", "बिलासपुर", "Chhattisgarh", "Bilaspur", 22.0797, 82.1409, 330106, "Mahanadi", "Arpa", False, "Mahanadi"),
    ("jagdalpur", "Jagdalpur", "जगदलपुर", "Chhattisgarh", "Bastar", 19.0748, 82.0080, 125463, "Godavari", "Indravati", False, "Godavari"),
    # Jharkhand
    ("ranchi", "Ranchi", "रांची", "Jharkhand", "Ranchi", 23.3441, 85.3096, 1073427, "Subarnarekha", "Subarnarekha", False, "Subarnarekha"),
    ("jamshedpur", "Jamshedpur", "जमशेदपुर", "Jharkhand", "East Singhbhum", 22.8046, 86.2029, 1339438, "Subarnarekha", "Subarnarekha", False, "Subarnarekha"),
    ("dhanbad", "Dhanbad", "धनबाद", "Jharkhand", "Dhanbad", 23.7957, 86.4304, 1162472, "Damodar", "Damodar", False, "Ganga"),
    # Punjab
    ("ludhiana", "Ludhiana", "लुधियाना", "Punjab", "Ludhiana", 30.9010, 75.8573, 1618879, "Sutlej", "Sutlej", False, "Indus"),
    ("patiala", "Patiala", "पटियाला", "Punjab", "Patiala", 30.3398, 76.3869, 406192, "Ghaggar", "Ghaggar", False, "Indus"),
    ("amritsar", "Amritsar", "अमृतसर", "Punjab", "Amritsar", 31.6340, 74.8723, 1132383, "Ravi / Beas", "Ravi", False, "Indus"),
    # Haryana
    ("ambala", "Ambala", "अंबाला", "Haryana", "Ambala", 30.3782, 76.7767, 207934, "Ghaggar", "Tangri", False, "Indus"),
    ("gurugram", "Gurugram", "गुरुग्राम", "Haryana", "Gurugram", 28.4595, 77.0266, 876969, "Sahibi", "Sahibi", False, "Ganga"),
    ("yamunanagar", "Yamunanagar", "यमुनानगर", "Haryana", "Yamunanagar", 30.1290, 77.2674, 216628, "Yamuna", "Yamuna", False, "Ganga"),
    # Himachal Pradesh
    ("mandi", "Mandi", "मंडी", "Himachal Pradesh", "Mandi", 31.7084, 76.9320, 26422, "Beas", "Beas", False, "Indus"),
    ("kullu", "Kullu", "कुल्लू", "Himachal Pradesh", "Kullu", 31.9579, 77.1095, 18536, "Beas", "Beas", False, "Indus"),
    ("shimla", "Shimla", "शिमला", "Himachal Pradesh", "Shimla", 31.1048, 77.1734, 169578, "Sutlej", "Sutlej", False, "Indus"),
    # Uttarakhand
    ("dehradun", "Dehradun", "देहरादून", "Uttarakhand", "Dehradun", 30.3165, 78.0322, 578420, "Ganga / Yamuna", "Song", False, "Ganga"),
    ("rishikesh", "Rishikesh", "ऋषिकेश", "Uttarakhand", "Dehradun", 30.0869, 78.2676, 102138, "Ganga", "Ganga", False, "Ganga"),
    ("chamoli", "Chamoli (Joshimath)", "चमोली", "Uttarakhand", "Chamoli", 30.5550, 79.5650, 16709, "Alaknanda", "Dhauliganga", False, "Ganga"),
    # Jammu & Kashmir, Ladakh, Chandigarh
    ("jammu", "Jammu", "जम्मू", "Jammu and Kashmir", "Jammu", 32.7266, 74.8570, 502197, "Chenab", "Tawi", False, "Indus"),
    ("leh", "Leh", "लेह", "Ladakh", "Leh", 34.1526, 77.5771, 30870, "Indus", "Indus", False, "Indus"),
    ("chandigarh", "Chandigarh", "चंडीगढ़", "Chandigarh", "Chandigarh", 30.7333, 76.7794, 960787, "Ghaggar", "Sukhna Choe", False, "Indus"),
    # Uttar Pradesh
    ("kanpur", "Kanpur", "कानपुर", "Uttar Pradesh", "Kanpur Nagar", 26.4499, 80.3319, 2765348, "Ganga", "Ganga", False, "Ganga"),
    ("bahraich", "Bahraich", "बहराइच", "Uttar Pradesh", "Bahraich", 27.5743, 81.5962, 186241, "Ghaghra", "Ghaghra", False, "Ganga"),
    ("ballia", "Ballia", "बलिया", "Uttar Pradesh", "Ballia", 25.7584, 84.1487, 104424, "Ganga", "Ganga", False, "Ganga"),
    ("ayodhya", "Ayodhya", "अयोध्या", "Uttar Pradesh", "Ayodhya", 26.7922, 82.1998, 55890, "Ghaghra", "Saryu", False, "Ganga"),
    # Bihar
    ("supaul", "Supaul", "सुपौल", "Bihar", "Supaul", 26.1233, 86.6040, 65437, "Kosi", "Kosi", False, "Ganga"),
    ("purnia", "Purnia", "पूर्णिया", "Bihar", "Purnia", 25.7771, 87.4753, 282248, "Kosi", "Saura", False, "Ganga"),
    # West Bengal
    ("coochbehar", "Cooch Behar", "कूचबिहार", "West Bengal", "Cooch Behar", 26.3452, 89.4482, 77935, "Torsa", "Torsa", False, "Brahmaputra"),
    # Assam
    ("barpeta", "Barpeta", "बरपेटा", "Assam", "Barpeta", 26.3226, 91.0060, 42649, "Brahmaputra", "Beki", False, "Brahmaputra"),
    ("lakhimpur", "North Lakhimpur", "लखीमपुर", "Assam", "Lakhimpur", 27.2350, 94.1030, 59814, "Brahmaputra", "Subansiri", False, "Brahmaputra"),
    # North-east
    ("gangtok", "Gangtok", "गंगटोक", "Sikkim", "East Sikkim", 27.3389, 88.6065, 100286, "Teesta", "Teesta", False, "Brahmaputra"),
    ("itanagar", "Itanagar", "ईटानगर", "Arunachal Pradesh", "Papum Pare", 27.0844, 93.6053, 59490, "Brahmaputra", "Dikrong", False, "Brahmaputra"),
    ("pasighat", "Pasighat", "पासीघाट", "Arunachal Pradesh", "East Siang", 28.0660, 95.3260, 24656, "Brahmaputra", "Siang", False, "Brahmaputra"),
    ("dimapur", "Dimapur", "दीमापुर", "Nagaland", "Dimapur", 25.9063, 93.7272, 122834, "Dhansiri", "Dhansiri", False, "Brahmaputra"),
    ("kohima", "Kohima", "कोहिमा", "Nagaland", "Kohima", 25.6751, 94.1086, 99039, "Barak", "Dzuza", False, "Barak"),
    ("aizawl", "Aizawl", "आइज़ोल", "Mizoram", "Aizawl", 23.7271, 92.7176, 293416, "Barak", "Tlawng", False, "Barak"),
    ("shillong", "Shillong", "शिलांग", "Meghalaya", "East Khasi Hills", 25.5788, 91.8933, 143229, "Umiam", "Umiam", False, "Brahmaputra"),
    ("tura", "Tura", "तुरा", "Meghalaya", "West Garo Hills", 25.5145, 90.2020, 74858, "Brahmaputra", "Simsang", False, "Brahmaputra"),
    # Odisha
    ("puri", "Puri", "पुरी", "Odisha", "Puri", 19.8135, 85.8312, 200564, "Mahanadi delta", "Bhargavi", True, "Mahanadi"),
    ("sambalpur", "Sambalpur", "संबलपुर", "Odisha", "Sambalpur", 21.4669, 83.9812, 183383, "Mahanadi", "Mahanadi", False, "Mahanadi"),
    # Andhra Pradesh, Telangana
    ("visakhapatnam", "Visakhapatnam", "विशाखापत्तनम", "Andhra Pradesh", "Visakhapatnam", 17.6868, 83.2185, 1728128, "Coastal", "Meghadri Gedda", True, "East Flowing Rivers"),
    ("nellore", "Nellore", "नेल्लोर", "Andhra Pradesh", "Nellore", 14.4426, 79.9865, 499575, "Pennar", "Pennar", True, "Pennar"),
    ("bhadrachalam", "Bhadrachalam", "भद्राचलम", "Telangana", "Bhadradri Kothagudem", 17.6688, 80.8936, 50087, "Godavari", "Godavari", False, "Godavari"),
    ("warangal", "Warangal", "वारंगल", "Telangana", "Hanamkonda", 17.9689, 79.5941, 704570, "Godavari", "Bhadrakali", False, "Godavari"),
    # Tamil Nadu, Puducherry
    ("madurai", "Madurai", "मदुरै", "Tamil Nadu", "Madurai", 9.9252, 78.1198, 1017865, "Vaigai", "Vaigai", False, "East Flowing Rivers"),
    ("tirunelveli", "Tirunelveli", "तिरुनेलवेली", "Tamil Nadu", "Tirunelveli", 8.7139, 77.7567, 473637, "Tamirabarani", "Tamirabarani", False, "East Flowing Rivers"),
    ("puducherry", "Puducherry", "पुदुचेरी", "Puducherry", "Puducherry", 11.9416, 79.8083, 244377, "Sankaraparani", "Sankaraparani", True, "East Flowing Rivers"),
    # Kerala
    ("thiruvananthapuram", "Thiruvananthapuram", "तिरुवनंतपुरम", "Kerala", "Thiruvananthapuram", 8.5241, 76.9366, 752490, "Karamana", "Karamana", True, "West Flowing Rivers"),
    ("kozhikode", "Kozhikode", "कोझिकोड", "Kerala", "Kozhikode", 11.2588, 75.7804, 609224, "Chaliyar", "Chaliyar", True, "West Flowing Rivers"),
    # Karnataka
    ("belagavi", "Belagavi", "बेलगावी", "Karnataka", "Belagavi", 15.8497, 74.4977, 490045, "Krishna", "Markandeya", False, "Krishna"),
    ("mangaluru", "Mangaluru", "मंगलुरु", "Karnataka", "Dakshina Kannada", 12.9141, 74.8560, 484785, "Netravati", "Netravati", True, "West Flowing Rivers"),
    ("madikeri", "Madikeri (Kodagu)", "मडिकेरी", "Karnataka", "Kodagu", 12.4244, 75.7382, 33381, "Cauvery", "Cauvery", False, "Cauvery"),
    # Gujarat, Maharashtra, Goa, DNH&DD
    ("rajkot", "Rajkot", "राजकोट", "Gujarat", "Rajkot", 22.3039, 70.8022, 1286678, "Aji", "Aji", False, "West Flowing Rivers"),
    ("junagadh", "Junagadh", "जूनागढ़", "Gujarat", "Junagadh", 21.5222, 70.4579, 320250, "Sonrakh", "Kalwa", False, "West Flowing Rivers"),
    ("bharuch", "Bharuch", "भरूच", "Gujarat", "Bharuch", 21.7051, 72.9959, 169007, "Narmada", "Narmada", True, "Narmada"),
    ("nashik", "Nashik", "नाशिक", "Maharashtra", "Nashik", 19.9975, 73.7898, 1486053, "Godavari", "Godavari", False, "Godavari"),
    ("chiplun", "Chiplun", "चिपळूण", "Maharashtra", "Ratnagiri", 17.5319, 73.5150, 55139, "Vashishti", "Vashishti", False, "West Flowing Rivers"),
    ("panaji", "Panaji", "पणजी", "Goa", "North Goa", 15.4909, 73.8278, 114759, "Mandovi", "Mandovi", True, "West Flowing Rivers"),
    ("daman", "Daman", "दमण", "Dadra and Nagar Haveli and Daman and Diu", "Daman", 20.3974, 72.8328, 39737, "Damanganga", "Damanganga", True, "West Flowing Rivers"),
    ("silvassa", "Silvassa", "सिलवासा", "Dadra and Nagar Haveli and Daman and Diu", "Dadra and Nagar Haveli", 20.2766, 73.0169, 98265, "Damanganga", "Damanganga", False, "West Flowing Rivers"),
    # Islands
    ("portblair", "Port Blair", "पोर्ट ब्लेयर", "Andaman and Nicobar Islands", "South Andaman", 11.6234, 92.7265, 100608, "Island", "—", True, "Islands"),
    ("kavaratti", "Kavaratti", "कवरत्ती", "Lakshadweep", "Lakshadweep", 10.5667, 72.6417, 11221, "Island", "—", True, "Islands"),
]

# location_id, date, precision, severity, driver, headline
EVENTS = [
    ("chiplun", "2021-07-22", "day", 3, "extreme_rainfall", "Vashishti overflowed; Chiplun town under several metres of water"),
    ("mandi", "2023-07-10", "day", 3, "river_discharge", "Beas in extreme spate during the July 2023 Himachal floods"),
    ("kullu", "2023-07-10", "day", 3, "river_discharge", "Beas washed away roads and bridges across Kullu–Manali"),
    ("shimla", "2023-08-14", "day", 3, "landslide", "Summer Hill landslide during extreme August 2023 rain"),
    ("gangtok", "2023-10-04", "day", 3, "glof", "South Lhonak GLOF flood wave down the Teesta through Sikkim"),
    ("leh", "2010-08-06", "day", 3, "extreme_rainfall", "Leh cloudburst — flash floods and debris flows through the town"),
    ("chamoli", "2021-02-07", "day", 3, "glof", "Rishiganga–Dhauliganga flash flood destroyed hydro projects"),
    ("rishikesh", "2013-06-17", "day", 2, "river_discharge", "Ganga in extreme spate during the Uttarakhand disaster"),
    ("patiala", "2023-07-10", "day", 2, "river_discharge", "Ghaggar and its tributaries flooded Patiala and Rajpura"),
    ("ludhiana", "2023-07-10", "month", 2, "river_discharge", "Sutlej belt flooding during the July 2023 Punjab floods"),
    ("ambala", "2023-07-09", "day", 2, "river_discharge", "Tangri overflowed into Ambala Cantt after record rain"),
    ("yamunanagar", "2023-07-11", "day", 2, "dam_release", "Record Hathnikund barrage release on the Yamuna"),
    ("chandigarh", "2023-07-09", "day", 2, "extreme_rainfall", "Record July rainfall, Sukhna floodgates opened, city waterlogged"),
    ("aizawl", "2024-05-28", "day", 3, "cyclone", "Cyclone Remal rain triggered deadly landslides around Aizawl"),
    ("madikeri", "2018-08-16", "day", 3, "landslide", "Kodagu landslides and floods during the August 2018 monsoon"),
    ("belagavi", "2019-08-07", "month", 2, "river_discharge", "Krishna basin floods across northern Karnataka"),
    ("kozhikode", "2019-08-08", "month", 2, "extreme_rainfall", "Chaliyar flooding during the August 2019 Kerala rains"),
    ("puri", "2019-05-03", "day", 3, "cyclone", "Cyclone Fani landfall near Puri"),
    ("nellore", "2021-11-19", "day", 3, "river_discharge", "Pennar floods after extreme north-east monsoon rain"),
    ("visakhapatnam", "2014-10-12", "day", 3, "cyclone", "Cyclone Hudhud landfall at Visakhapatnam"),
    ("bhadrachalam", "2022-07-15", "day", 3, "river_discharge", "Godavari crossed 70 ft at Bhadrachalam, highest in decades"),
    ("warangal", "2020-08-16", "month", 2, "extreme_rainfall", "Tri-city flooding after sustained heavy rain"),
    ("tirunelveli", "2023-12-18", "day", 3, "extreme_rainfall", "Extreme rain flooded Tirunelveli and Thoothukudi"),
    ("junagadh", "2023-07-22", "day", 2, "extreme_rainfall", "Flash floods swept vehicles through Junagadh city"),
    ("bharuch", "2023-09-17", "day", 3, "dam_release", "Narmada flood after high Sardar Sarovar outflow"),
    ("nashik", "2019-08-04", "month", 2, "river_discharge", "Godavari in spate through Nashik after Gangapur release"),
    ("kota", "2019-09-15", "month", 2, "dam_release", "Chambal flooding in Kota after high dam releases"),
    ("narmadapuram", "2020-08-30", "day", 3, "river_discharge", "Narmada in record flood at Hoshangabad"),
    ("gwalior", "2021-08-04", "month", 2, "river_discharge", "Gwalior–Chambal region floods, Sindh river in spate"),
    ("supaul", "2008-08-18", "day", 3, "river_discharge", "Kosi embankment breach at Kusaha changed the river's course"),
    ("purnia", "2008-08-20", "month", 3, "river_discharge", "Kosi flood spread across Purnia division"),
    ("bahraich", "2017-08-20", "month", 2, "river_discharge", "Ghaghra floods across the Terai districts"),
    ("ballia", "2016-08-22", "month", 2, "river_discharge", "Ganga above danger level, erosion and flooding"),
    ("coochbehar", "2017-08-13", "month", 3, "river_discharge", "North Bengal floods, Torsa and Raidak in spate"),
    ("barpeta", "2022-06-18", "month", 3, "river_discharge", "Among the worst-hit districts of the June 2022 Assam floods"),
    ("lakhimpur", "2020-07-15", "month", 2, "river_discharge", "Subansiri and Ranganadi flooding in upper Assam"),
    ("jammu", "2014-09-06", "month", 2, "river_discharge", "Tawi and Chenab in spate during the September 2014 floods"),
    ("barmer", "2006-08-22", "month", 3, "extreme_rainfall", "Desert flood inundated Kawas and villages across Barmer"),
    ("sambalpur", "2011-09-10", "month", 2, "river_discharge", "Mahanadi flood with high Hirakud releases"),
    ("puducherry", "2015-12-01", "month", 2, "extreme_rainfall", "Heavy north-east monsoon rain, widespread waterlogging"),
]


def main() -> None:
    loc_path = DATA / "locations.json"
    payload = json.loads(loc_path.read_text(encoding="utf-8"))
    have = {l["id"] for l in payload["locations"]}
    added = 0
    for row in NEW:
        if row[0] in have:
            continue
        keys = ["id", "name", "name_hi", "state", "district", "lat", "lon", "population", "basin", "river", "coastal", "cwc_basin"]
        payload["locations"].append(dict(zip(keys, row)))
        added += 1
    payload["_meta"]["count"] = len(payload["locations"])
    payload["_meta"]["description"] = (
        "Monitored location set for the JalDrishti prototype: every Indian state and union territory, "
        "with additional flood-prone towns in the large riverine and coastal states."
    )
    loc_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    ev_path = DATA / "historical_floods.json"
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    seen = {(e["location_id"], e["date"]) for e in ev["events"]}
    new_ev = 0
    for lid, d, prec, sev, driver, headline in EVENTS:
        if (lid, d) in seen:
            continue
        ev["events"].append({"location_id": lid, "date": d, "date_precision": prec, "severity": sev, "driver": driver, "headline": headline})
        new_ev += 1
    ev["_meta"]["count"] = len(ev["events"])
    ev_path.write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")

    states = {l["state"] for l in payload["locations"]}
    print(f"added {added} locations -> {len(payload['locations'])} total across {len(states)} states/UTs")
    print(f"added {new_ev} events -> {len(ev['events'])} total")


if __name__ == "__main__":
    main()
