"""EduChats → Maps tab: people on EduChats across India as coloured pins.

Anyone signed in to EduChats sees the map; account holders can add themselves
with their location and pick what others see (name, username, email, city,
photo, bio). A spot is rounded to about 1 km so nobody's exact home shows.
Demo pins (ChatUser.is_demo) only ever say "User N".
"""
from datetime import timedelta

from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ChatUser, MapSpot
from .support_chat import ONLINE_SECONDS, _fail, _json_body, current_user, is_superuser_viewer

# pin colour groups (the legend on the map)
REGIONS = {
    'north': {'Delhi', 'Punjab', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir', 'Ladakh', 'Uttarakhand',
              'Chandigarh', 'Uttar Pradesh'},
    'central': {'Madhya Pradesh', 'Chhattisgarh'},
    'east': {'Bihar', 'Jharkhand', 'Odisha', 'West Bengal'},
    'northeast': {'Assam', 'Meghalaya', 'Manipur', 'Tripura', 'Mizoram', 'Nagaland', 'Arunachal Pradesh', 'Sikkim'},
    'west': {'Maharashtra', 'Gujarat', 'Rajasthan', 'Goa', 'Dadra and Nagar Haveli and Daman and Diu'},
    'south': {'Karnataka', 'Tamil Nadu', 'Kerala', 'Andhra Pradesh', 'Telangana', 'Puducherry',
              'Andaman and Nicobar Islands', 'Lakshadweep'},
}
SHOW_FIELDS = ('show_name', 'show_username', 'show_email', 'show_city', 'show_photo', 'show_bio')
# roughly India, so a typo or a far-away GPS fix doesn't land a pin in the sea
LAT_RANGE, LNG_RANGE = (6.0, 37.6), (68.0, 97.5)


def region_for(state):
    for key, states in REGIONS.items():
        if state in states:
            return key
    return 'central'


def _pin(spot, me, online_since):
    u = spot.user
    pin = {'n': spot.pk, 'lat': spot.latitude, 'lng': spot.longitude, 'r': region_for(spot.state)}
    if u.is_demo:
        return pin
    pin['me'] = u.pk == me.pk
    pin['on'] = bool(u.show_last_seen and u.last_seen_at and u.last_seen_at >= online_since)
    d = {}
    if spot.show_name:
        d['name'] = u.name
    if spot.show_username and u.username:
        d['username'] = u.username
    if spot.show_email:
        d['email'] = u.email
    if spot.show_city:
        d['city'] = ', '.join(x for x in (spot.city, spot.state) if x)
    if spot.show_photo and u.photo:
        d['photo'] = reverse('chats_user_photo', args=[u.pk])
    if spot.show_bio and u.bio:
        d['bio'] = u.bio
    pin['d'] = d
    return pin


def _mine(spot):
    if not spot:
        return None
    return dict({k: getattr(spot, k) for k in SHOW_FIELDS}, n=spot.pk, visible=spot.visible,
                lat=spot.latitude, lng=spot.longitude, city=spot.city, state=spot.state)


def api_map(request):
    """GET: every visible pin, a few totals and the viewer's own spot."""
    me = current_user(request)
    if not me:
        return _fail('Please log in again.', 401)
    online_since = timezone.now() - timedelta(seconds=ONLINE_SECONDS * 3)
    spots = (MapSpot.objects.filter(visible=True).select_related('user')
             .filter(user__is_guest=False).exclude(user__is_active=False, user__is_demo=False))
    pins = [_pin(s, me, online_since) for s in spots]
    mine = MapSpot.objects.filter(user=me).first() if not me.is_guest else None
    super_view = is_superuser_viewer(request, me)
    return JsonResponse({
        'ok': True, 'pins': pins, 'mine': _mine(mine),
        'states': len({s.state for s in spots if s.state}), 'cities': len({s.city for s in spots if s.city}),
        'can_join': not me.is_guest,
        'demo': ChatUser.objects.filter(is_demo=True).count() if super_view else None,
    })


@require_POST
def api_map_me(request):
    """POST {action: 'save', lat, lng, visible, show_*} or {action: 'remove'}."""
    me = current_user(request)
    if not me:
        return _fail('Please log in again.', 401)
    if me.is_guest:
        return _fail('Sign up or log in to add yourself to the map.', 403)
    data = _json_body(request)
    if data.get('action') == 'remove':
        MapSpot.objects.filter(user=me).delete()
        return JsonResponse({'ok': True, 'mine': None})
    spot = MapSpot.objects.filter(user=me).first() or MapSpot(user=me)
    if 'lat' in data or not spot.pk:
        try:
            lat, lng = float(data.get('lat')), float(data.get('lng'))
        except (TypeError, ValueError):
            return _fail('Turn on location so we can find where you are.')
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]):
            return _fail('The EduChats map covers India only for now.')
        spot.latitude, spot.longitude = round(lat, 2), round(lng, 2)
    spot.city, spot.state = me.city[:80], me.state[:60]
    if 'visible' in data:
        spot.visible = bool(data.get('visible'))
    for key in SHOW_FIELDS:
        if key in data:
            setattr(spot, key, bool(data.get(key)))
    spot.save()
    return JsonResponse({'ok': True, 'mine': _mine(spot)})


@require_POST
def api_map_demo(request):
    """Superuser: remove the sample users (exampleN@gmail.com) and their pins."""
    me = current_user(request)
    if not me or not is_superuser_viewer(request, me):
        return _fail('Only the site owner can do this.', 403)
    n = ChatUser.objects.filter(is_demo=True).count()
    ChatUser.objects.filter(is_demo=True).delete()
    return JsonResponse({'ok': True, 'deleted': n})
