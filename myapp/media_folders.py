"""Where every uploaded file lives inside Dropbox '/EduTrellis Site/':

    website/   the main site and store
        accounts/avatars/            customer profile pictures
        store/categories/            store category images
        store/products/              product covers (+ gallery/, colors/, videos/)
        home/hero/                   homepage slider
        home/services/               homepage Products & Services cards
        blog/                        homepage blog gallery
        about/                       About section (+ founder/)
        branding/                    favicon, link-preview image (+ pwa/ app icon)
    ai/        EduTrellis AI (/ai/)
        branding/                    AI favicon (+ social/, pwa/)
        uploads/YYYY/MM/DD/          pictures people attach to AI chats
        generated/YYYY/MM/DD/        AI-made images (AI chat and EduChats AI)
        videos/YYYY/MM/DD/           AI-made videos
        calls/<user>/                voice call recordings            (private)
        archive/<email>/             per-account copy of AI images    (private)
    educhats/  EduChats (/educhats/)                                  (all private)
        users/photos/, users/covers/ profile pictures and covers
        support/YYYY/MM/, support/profile/   Support chat files and its picture
        dm/YYYY/MM/                  direct-message attachments
        groups/photos/, groups/YYYY/MM/      group pictures and attachments
        stories/YYYY/MM/             stories
        app/                         the EduChats app icon

Files saved before this layout used the old top-level folders on the left of
LEGACY_FOLDERS; the organize_media command moves them (Dropbox, database
rows and saved links), and /media/<old name> keeps working meanwhile.
"""

# website
AVATARS = 'website/accounts/avatars/'
CATEGORIES = 'website/store/categories/'
PRODUCTS = 'website/store/products/'
PRODUCT_GALLERY = PRODUCTS + 'gallery/'
PRODUCT_COLORS = PRODUCTS + 'colors/'
PRODUCT_VIDEOS = PRODUCTS + 'videos/'
HERO = 'website/home/hero/'
SERVICES = 'website/home/services/'
BLOG = 'website/blog/'
ABOUT = 'website/about/'
FOUNDER = 'website/about/founder/'
BRANDING = 'website/branding/'
PWA = 'website/branding/pwa/'

# EduTrellis AI
AI_BRANDING = 'ai/branding/'
AI_SOCIAL = 'ai/branding/social/'
AI_PWA = 'ai/branding/pwa/'
AI_UPLOADS = 'ai/uploads/'
AI_GENERATED = 'ai/generated/'
AI_VIDEOS = 'ai/videos/'
AI_CALLS = 'ai/calls/'
AI_ARCHIVE = 'ai/archive'          # dropbox_images.py: '/EduTrellis Site/ai/archive/<email>/…'

# EduChats
CHAT_USER_PHOTOS = 'educhats/users/photos/'
CHAT_USER_COVERS = 'educhats/users/covers/'
SUPPORT_FILES = 'educhats/support/%Y/%m/'
SUPPORT_PROFILE = 'educhats/support/profile/'
DM_FILES = 'educhats/dm/%Y/%m/'
GROUP_PHOTOS = 'educhats/groups/photos/'
GROUP_FILES = 'educhats/groups/%Y/%m/'
STORIES = 'educhats/stories/%Y/%m/'
CHATS_APP = 'educhats/app/'

# Old folder -> new folder. Order matters: a more specific folder comes before
# the folder that contains it (support_chat/users/ before support_chat/).
LEGACY_FOLDERS = [
    ('support_chat/users/', CHAT_USER_PHOTOS),
    ('support_chat/covers/', CHAT_USER_COVERS),
    ('support_chat/profile/', SUPPORT_PROFILE),
    ('support_chat/groups/', GROUP_PHOTOS),
    ('support_chat/app/', CHATS_APP),
    ('support_chat/', 'educhats/support/'),
    ('ai_branding/', AI_BRANDING),
    ('ai_uploads/', AI_UPLOADS),
    ('ai_generated/', AI_GENERATED),
    ('ai_videos/', AI_VIDEOS),
    ('ai_calls/', AI_CALLS),
    ('avatars/', AVATARS),
    ('categories/', CATEGORIES),
    ('products_home/', SERVICES),
    ('products/', PRODUCTS),
    ('hero/', HERO),
    ('blog/', BLOG),
    ('about/', ABOUT),
    ('founder/', FOUNDER),
    ('pwa/', PWA),
    ('customize/', BRANDING),
]


def new_name(name):
    """The organized name for a file saved under an old folder, else ''."""
    name = (name or '').replace('\\', '/')
    for old, new in LEGACY_FOLDERS:
        if name.startswith(old):
            return new + name[len(old):]
    return ''
