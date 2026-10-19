"""300 sample people for the EduChats Maps tab, spread over Indian cities.

Each one is a turned-off account (no login, not in search) with the email
exampleN@gmail.com (N = 1…300), so they are easy to find and delete later:
`python manage.py educhats_demo_users --delete`, or "Remove demo users" in the
Maps tab (superuser). The map itself only ever shows them as "User N".
"""
import random

from django.contrib.auth.hashers import make_password
from django.db import migrations

TOTAL = 300

# city, state, latitude, longitude, weight (bigger cities get more people)
CITIES = [
    ('New Delhi', 'Delhi', 28.6139, 77.2090, 12), ('Mumbai', 'Maharashtra', 19.0760, 72.8777, 12),
    ('Bengaluru', 'Karnataka', 12.9716, 77.5946, 12), ('Hyderabad', 'Telangana', 17.3850, 78.4867, 10),
    ('Chennai', 'Tamil Nadu', 13.0827, 80.2707, 10), ('Kolkata', 'West Bengal', 22.5726, 88.3639, 10),
    ('Pune', 'Maharashtra', 18.5204, 73.8567, 8), ('Ahmedabad', 'Gujarat', 23.0225, 72.5714, 8),
    ('Jaipur', 'Rajasthan', 26.9124, 75.7873, 7), ('Lucknow', 'Uttar Pradesh', 26.8467, 80.9462, 8),
    ('Kanpur', 'Uttar Pradesh', 26.4499, 80.3319, 4), ('Varanasi', 'Uttar Pradesh', 25.3176, 82.9739, 4),
    ('Prayagraj', 'Uttar Pradesh', 25.4358, 81.8463, 4), ('Agra', 'Uttar Pradesh', 27.1767, 78.0081, 3),
    ('Noida', 'Uttar Pradesh', 28.5355, 77.3910, 5), ('Gorakhpur', 'Uttar Pradesh', 26.7606, 83.3732, 3),
    ('Patna', 'Bihar', 25.5941, 85.1376, 6), ('Gaya', 'Bihar', 24.7914, 85.0002, 2),
    ('Ranchi', 'Jharkhand', 23.3441, 85.3096, 4), ('Jamshedpur', 'Jharkhand', 22.8046, 86.2029, 3),
    ('Bhubaneswar', 'Odisha', 20.2961, 85.8245, 4), ('Cuttack', 'Odisha', 20.4625, 85.8830, 2),
    ('Guwahati', 'Assam', 26.1445, 91.7362, 4), ('Shillong', 'Meghalaya', 25.5788, 91.8933, 2),
    ('Imphal', 'Manipur', 24.8170, 93.9368, 2), ('Agartala', 'Tripura', 23.8315, 91.2868, 2),
    ('Aizawl', 'Mizoram', 23.7271, 92.7176, 1), ('Kohima', 'Nagaland', 25.6751, 94.1086, 1),
    ('Itanagar', 'Arunachal Pradesh', 27.0844, 93.6053, 1), ('Gangtok', 'Sikkim', 27.3389, 88.6065, 1),
    ('Siliguri', 'West Bengal', 26.7271, 88.3953, 2), ('Bhopal', 'Madhya Pradesh', 23.2599, 77.4126, 5),
    ('Indore', 'Madhya Pradesh', 22.7196, 75.8577, 5), ('Gwalior', 'Madhya Pradesh', 26.2183, 78.1828, 2),
    ('Jabalpur', 'Madhya Pradesh', 23.1815, 79.9864, 2), ('Raipur', 'Chhattisgarh', 21.2514, 81.6296, 3),
    ('Bilaspur', 'Chhattisgarh', 22.0797, 82.1409, 1), ('Nagpur', 'Maharashtra', 21.1458, 79.0882, 4),
    ('Nashik', 'Maharashtra', 19.9975, 73.7898, 3), ('Aurangabad', 'Maharashtra', 19.8762, 75.3433, 2),
    ('Surat', 'Gujarat', 21.1702, 72.8311, 5), ('Vadodara', 'Gujarat', 22.3072, 73.1812, 3),
    ('Rajkot', 'Gujarat', 22.3039, 70.8022, 3), ('Udaipur', 'Rajasthan', 24.5854, 73.7125, 2),
    ('Jodhpur', 'Rajasthan', 26.2389, 73.0243, 2), ('Kota', 'Rajasthan', 25.2138, 75.8648, 3),
    ('Bikaner', 'Rajasthan', 28.0229, 73.3119, 1), ('Panaji', 'Goa', 15.4909, 73.8278, 2),
    ('Chandigarh', 'Chandigarh', 30.7333, 76.7794, 3), ('Ludhiana', 'Punjab', 30.9010, 75.8573, 3),
    ('Amritsar', 'Punjab', 31.6340, 74.8723, 3), ('Jalandhar', 'Punjab', 31.3260, 75.5762, 2),
    ('Gurugram', 'Haryana', 28.4595, 77.0266, 5), ('Faridabad', 'Haryana', 28.4089, 77.3178, 3),
    ('Panipat', 'Haryana', 29.3909, 76.9635, 1), ('Dehradun', 'Uttarakhand', 30.3165, 78.0322, 3),
    ('Haridwar', 'Uttarakhand', 29.9457, 78.1642, 1), ('Shimla', 'Himachal Pradesh', 31.1048, 77.1734, 2),
    ('Dharamshala', 'Himachal Pradesh', 32.2190, 76.3234, 1), ('Srinagar', 'Jammu and Kashmir', 34.0837, 74.7973, 2),
    ('Jammu', 'Jammu and Kashmir', 32.7266, 74.8570, 2), ('Leh', 'Ladakh', 34.1526, 77.5771, 1),
    ('Mysuru', 'Karnataka', 12.2958, 76.6394, 3), ('Mangaluru', 'Karnataka', 12.9141, 74.8560, 2),
    ('Hubballi', 'Karnataka', 15.3647, 75.1240, 2), ('Coimbatore', 'Tamil Nadu', 11.0168, 76.9558, 4),
    ('Madurai', 'Tamil Nadu', 9.9252, 78.1198, 3), ('Tiruchirappalli', 'Tamil Nadu', 10.7905, 78.7047, 2),
    ('Kochi', 'Kerala', 9.9312, 76.2673, 4), ('Thiruvananthapuram', 'Kerala', 8.5241, 76.9366, 3),
    ('Kozhikode', 'Kerala', 11.2588, 75.7804, 2), ('Visakhapatnam', 'Andhra Pradesh', 17.6868, 83.2185, 4),
    ('Vijayawada', 'Andhra Pradesh', 16.5062, 80.6480, 3), ('Tirupati', 'Andhra Pradesh', 13.6288, 79.4192, 2),
    ('Warangal', 'Telangana', 17.9689, 79.5941, 2), ('Puducherry', 'Puducherry', 11.9416, 79.8083, 1),
    ('Port Blair', 'Andaman and Nicobar Islands', 11.6234, 92.7265, 1),
]
FIRST = ['Aarav', 'Vivaan', 'Aditya', 'Arjun', 'Sai', 'Reyansh', 'Krishna', 'Ishaan', 'Rohan', 'Kabir', 'Ananya', 'Diya',
         'Saanvi', 'Aadhya', 'Isha', 'Kavya', 'Priya', 'Riya', 'Neha', 'Pooja', 'Rahul', 'Amit', 'Vikram', 'Suresh', 'Karan',
         'Manish', 'Deepak', 'Nikhil', 'Harsh', 'Yash', 'Sneha', 'Meera', 'Lakshmi', 'Divya', 'Shreya', 'Tanvi', 'Anjali',
         'Simran', 'Gurpreet', 'Harpreet', 'Arnav', 'Dhruv', 'Om', 'Ayaan', 'Rudra', 'Pranav', 'Siddharth', 'Varun', 'Nisha',
         'Payal', 'Swati', 'Bhavna', 'Ritika', 'Aisha', 'Zoya', 'Farhan', 'Imran', 'Joseph', 'Mary', 'Lalit', 'Tenzin', 'Bhupen']
LAST = ['Sharma', 'Verma', 'Gupta', 'Singh', 'Kumar', 'Patel', 'Shah', 'Mehta', 'Reddy', 'Rao', 'Nair', 'Menon', 'Iyer',
        'Pillai', 'Das', 'Bose', 'Banerjee', 'Chatterjee', 'Mukherjee', 'Joshi', 'Kulkarni', 'Deshmukh', 'Patil', 'Yadav',
        'Mishra', 'Tiwari', 'Pandey', 'Dubey', 'Chauhan', 'Rathore', 'Gill', 'Sandhu', 'Khan', 'Ansari', 'Fernandes', 'Thomas',
        'Bora', 'Sangma', 'Lepcha', 'Naidu']


def create_demo_users(apps, schema_editor):
    ChatUser = apps.get_model('ai_app', 'ChatUser')
    MapSpot = apps.get_model('ai_app', 'MapSpot')
    rnd = random.Random(2026)
    weights = [c[4] for c in CITIES]
    taken = set(ChatUser.objects.filter(email__iregex=r'^example[0-9]+@gmail\.com$').values_list('email', flat=True))
    no_login = make_password(None)
    for n in range(1, TOTAL + 1):
        email = f'example{n}@gmail.com'
        city, state, lat, lng, _ = rnd.choices(CITIES, weights)[0]
        name = f'{rnd.choice(FIRST)} {rnd.choice(LAST)}'
        jitter = 0.02 if state == 'Andaman and Nicobar Islands' else 0.06
        spot_lat, spot_lng = lat + rnd.uniform(-jitter, jitter), lng + rnd.uniform(-jitter, jitter)
        if email in taken:
            continue
        user = ChatUser.objects.create(name=name, email=email, phone=f'00000{n:05d}', state=state, city=city,
                                       password=no_login, is_verified=False, is_active=False, is_demo=True)
        MapSpot.objects.create(user=user, latitude=round(spot_lat, 4), longitude=round(spot_lng, 4), city=city, state=state)


def delete_demo_users(apps, schema_editor):
    apps.get_model('ai_app', 'ChatUser').objects.filter(is_demo=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ai_app', '0029_map_spots'),
    ]

    operations = [
        migrations.RunPython(create_demo_users, delete_demo_users),
    ]
