#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# emoji.sh — Selector de emojis con rofi (Mod+E)
# Busca por nombre en inglés y copia el emoji al portapapeles
# (wl-copy en Wayland, xclip en X11).
# ──────────────────────────────────────────────────────────
THEME="$HOME/.config/rofi/theme.rasi"

emojis() {
    cat <<'EOF'
😀 Grinning Face
😃 Grinning Face with Big Eyes
😄 Grinning Face with Smiling Eyes
😁 Beaming Face with Smiling Eyes
😆 Grinning Squinting Face
😅 Grinning Face with Sweat
🤣 Rolling on the Floor Laughing
😂 Face with Tears of Joy
🙂 Slightly Smiling Face
🙃 Upside-Down Face
😉 Winking Face
😊 Smiling Face with Smiling Eyes
😇 Smiling Face with Halo
🥰 Smiling Face with Hearts
😍 Smiling Face with Heart-Eyes
🤩 Star-Struck
😘 Face Blowing a Kiss
😗 Kissing Face
😚 Kissing Face with Closed Eyes
😙 Kissing Face with Smiling Eyes
😋 Face Savoring Food
😛 Face with Tongue
😜 Winking Face with Tongue
🤩 Star-Struck
😝 Squinting Face with Tongue
🤑 Money-Mouth Face
🤗 Hugging Face
🤭 Face with Hand Over Mouth
🤫 Shushing Face
🤔 Thinking Face
🤐 Zipper-Mouth Face
🤨 Face with Raised Eyebrow
😐 Neutral Face
😑 Expressionless Face
😶 Face Without Mouth
😏 Smirking Face
😒 Unamused Face
🙄 Face with Rolling Eyes
😬 Grimacing Face
😌 Relieved Face
😔 Pensive Face
😪 Sleepy Face
🤤 Drooling Face
😴 Sleeping Face
😷 Face with Medical Mask
🤒 Face with Thermometer
🤕 Face with Head-Bandage
🤢 Nauseated Face
🤮 Face Vomiting
🤧 Sneezing Face
🥵 Hot Face
🥶 Cold Face
🥴 Woozy Face
😵 Dizzy Face
🤯 Exploding Head
🥳 Partying Face
😎 Smiling Face with Sunglasses
🤓 Nerd Face
🧐 Face with Monocle
😕 Confused Face
😟 Worried Face
🙁 Slightly Frowning Face
☹️ Frowning Face
😮 Face with Open Mouth
😯 Hushed Face
😰 Anxious Face with Sweat
😥 Sad but Relieved Face
😢 Crying Face
😭 Loudly Crying Face
😱 Face Screaming in Fear
😖 Confounded Face
😣 Persevering Face
😞 Disappointed Face
😓 Downcast Face with Sweat
😩 Weary Face
😫 Tired Face
🥱 Yawning Face
😤 Face with Steam From Nose
😡 Pouting Face
😠 Angry Face
🤬 Face with Symbols on Mouth
👋 Waving Hand
🤚 Raised Back of Hand
🖐️ Hand with Fingers Splayed
✋ Raised Hand
🖖 Vulcan Salute
👌 OK Hand
🤌 Pinched Fingers
🤏 Pinching Hand
✌️ Victory Hand
🤞 Crossed Fingers
🫰 Hand with Index Finger and Thumb Crossed
🤟 Love-You Gesture
🤘 Sign of the Horns
🤙 Call Me Hand
👈 Backhand Index Pointing Left
👉 Backhand Index Pointing Right
👆 Backhand Index Pointing Up
🖕 Middle Finger
👇 Backhand Index Pointing Down
☝️ Index Pointing Up
👍 Thumbs Up
👎 Thumbs Down
✊ Raised Fist
👊 Oncoming Fist
🤛 Left-Facing Fist
🤜 Right-Facing Fist
👏 Clapping Hands
🙌 Raising Hands
🫶 Heart Hands
👐 Open Hands
🤲 Palms Up Together
🤝 Handshake
🙏 Folded Hands
✍️ Writing Hand
💅 Nail Polish
🤳 Selfie
💪 Flexed Biceps
🦾 Mechanical Arm
🦿 Mechanical Leg
🦵 Leg
🦶 Foot
👂 Ear
🦻 Ear with Hearing Aid
👃 Nose
🧠 Brain
🫀 Heart
🫁 Lungs
🦷 Tooth
🦴 Bone
👀 Eyes
👁️ Eye
👅 Tongue
👄 Mouth
👶 Baby
🧒 Child
👦 Boy
👧 Girl
🧑 Person
👱 Person Blond Hair
👨 Man
🧔 Man Beard
👩 Woman
🧓 Older Person
👴 Old Man
👵 Old Woman
🙍 Person Frowning
🙎 Person Pouting
🙅 Person Gesturing No
🙆 Person Gesturing OK
💁 Person Tipping Hand
🙋 Person Raising Hand
🧏 Deaf Person
🙇 Person Bowing
🤦 Face Palm
🤷 Person Shrugging
👮 Police Officer
🕵️ Detective
💂 Guard
🥷 Ninja
👷 Construction Worker
🫅 Person with Crown
🤴 Prince
👸 Princess
👳 Person Wearing Turban
👲 Person with Skullcap
🧕 Woman with Headscarf
🤵 Person in Tuxedo
👰 Person with Veil
🤰 Pregnant Woman
🤱 Breast-Feeding
👼 Baby Angel
🎅 Santa Claus
🤶 Mrs Claus
🦸 Superhero
🦹 Supervillain
🧙 Mage
🧚 Fairy
🧛 Vampire
🧜 Merperson
🧝 Elf
🧞 Genie
🧟 Zombie
💆 Person Getting Massage
💇 Person Getting Haircut
🚶 Person Walking
🧍 Person Standing
🧎 Person Kneeling
🏃 Person Running
💃 Woman Dancing
🕺 Man Dancing
🕴️ Person in Suit Levitating
👯 People Party Popper
🧖 Person in Steamy Room
🧗 Person Climbing
🤸 Person Cartwheeling
🏋️ Person Lifting Weights
🚴 Person Biking
🚵 Person Mountain Biking
🏇 Horse Racing
🏂 Snowboarder
🏄 Person Surfing
🏊 Person Swimming
🤽 Person Playing Water Polo
🤾 Person Playing Handball
🧘 Person in Lotus Position
🛀 Person Taking Bath
🛌 Person in Bed
👩‍🤝‍👩 Women Holding Hands
👫 Man and Woman Holding Hands
👬 Men Holding Hands
🧑‍🤝‍🧑 People Holding Hands
👪 Family
💏 Kiss
💑 Couple with Heart
🗣️ Speaking Head
👤 Bust in Silhouette
👣 Footprints
🐵 Monkey Face
🐒 Monkey
🦍 Gorilla
🦧 Orangutan
🐶 Dog Face
🐕 Dog
🦮 Guide Dog
🐩 Poodle
🐺 Wolf
🦊 Fox
🦝 Raccoon
🐱 Cat Face
🐈 Cat
🦁 Lion
🐯 Tiger Face
🐅 Tiger
🐆 Leopard
🐴 Horse Face
🐎 Horse
🦄 Unicorn
🦓 Zebra
🦌 Deer
🦬 Bison
🐮 Cow Face
🐂 Ox
🐄 Cow
🐷 Pig Face
🐖 Pig
🐗 Boar
🐽 Pig Nose
🐏 Ram
🐑 Ewe
🐐 Goat
🐪 Camel
🐫 Two-Hump Camel
🦙 Llama
🦒 Giraffe
🐘 Elephant
🦣 Mammoth
🦏 Rhinoceros
🦛 Hippopotamus
🐭 Mouse Face
🐁 Mouse
🐀 Rat
🐹 Hamster
🐰 Rabbit Face
🐇 Rabbit
🐿️ Chipmunk
🦫 Beaver
🦔 Hedgehog
🦇 Bat
🐻 Bear
🐻‍❄️ Polar Bear
🐨 Koala
🐼 Panda
🦥 Sloth
🦦 Otter
🦨 Skunk
🦘 Kangaroo
🦡 Badger
🐾 Paw Prints
🦃 Turkey
🐔 Chicken
🐓 Rooster
🐣 Hatching Chick
🐤 Baby Chick
🐥 Front-Facing Baby Chick
🐦 Bird
🐧 Penguin
🕊️ Dove
🦅 Eagle
🦆 Duck
🦢 Swan
🦉 Owl
🦤 Dodo
🪶 Feather
🦩 Flamingo
🦚 Peacock
🦜 Parrot
🐸 Frog
🐊 Crocodile
🐢 Turtle
🦎 Lizard
🐍 Snake
🐲 Dragon Face
🐉 Dragon
🦕 Sauropod
🦖 T-Rex
🐳 Spouting Whale
🐋 Whale
🐬 Dolphin
🦭 Seal
🐟 Fish
🐠 Tropical Fish
🐡 Blowfish
🦈 Shark
🐙 Octopus
🐚 Spiral Shell
🪸 Coral
🐌 Snail
🦋 Butterfly
🐛 Bug
🐜 Ant
🐝 Honeybee
🪲 Beetle
🐞 Lady Beetle
🦗 Cricket
🪳 Cockroach
🕷️ Spider
🦂 Scorpion
🦟 Mosquito
🪰 Fly
🪱 Worm
🦠 Microbe
💐 Bouquet
🌸 Cherry Blossom
💮 White Flower
🏵️ Rosette
🌹 Rose
🥀 Wilted Flower
🌺 Hibiscus
🌻 Sunflower
🌼 Blossom
🌷 Tulip
🌱 Seedling
🪴 Potted Plant
🌲 Evergreen Tree
🌳 Deciduous Tree
🌴 Palm Tree
🌵 Cactus
🌾 Sheaf of Rice
🌿 Herb
☘️ Shamrock
🍀 Four Leaf Clover
🍁 Maple Leaf
🍂 Fallen Leaf
🍃 Leaf Fluttering in Wind
🍇 Grapes
🍈 Melon
🍉 Watermelon
🍊 Tangerine
🍋 Lemon
🍌 Banana
🍍 Pineapple
🥭 Mango
🍎 Red Apple
🍏 Green Apple
🍐 Pear
🍑 Peach
🍒 Cherries
🍓 Strawberry
🫐 Blueberries
🥝 Kiwi Fruit
🍅 Tomato
🫒 Olive
🥥 Coconut
🥑 Avocado
🍆 Eggplant
🥔 Potato
🥕 Carrot
🌽 Ear of Corn
🌶️ Hot Pepper
🫑 Bell Pepper
🥒 Cucumber
🥬 Leafy Green
🥦 Broccoli
🧄 Garlic
🧅 Onion
🍄 Mushroom
🥜 Peanuts
🫘 Beans
🌰 Chestnut
🍞 Bread
🥐 Croissant
🥖 Baguette Bread
🫓 Flatbread
🥨 Pretzel
🥯 Bagel
🥞 Pancakes
🧇 Waffle
🧀 Cheese Wedge
🍖 Meat on Bone
🍗 Poultry Leg
🥩 Cut of Meat
🥓 Bacon
🍔 Hamburger
🍟 French Fries
🍕 Pizza
🌭 Hot Dog
🥪 Sandwich
🌮 Taco
🌯 Burrito
🫔 Tamale
🥙 Stuffed Flatbread
🧆 Falafel
🥚 Egg
🍳 Cooking
🥘 Shallow Pan of Food
🍲 Pot of Food
🫕 Fondue
🥣 Bowl with Spoon
🥗 Green Salad
🍿 Popcorn
🧈 Butter
🧂 Salt
🥫 Canned Food
🍱 Bento Box
🍘 Rice Cracker
🍙 Rice Ball
🍚 Cooked Rice
🍛 Curry Rice
🍜 Steaming Bowl
🍝 Spaghetti
🍠 Roasted Sweet Potato
🍢 Oden
🍣 Sushi
🍤 Fried Shrimp
🍥 Fish Cake with Swirl
🥮 Moon Cake
🍡 Dango
🥟 Dumpling
🥠 Fortune Cookie
🥡 Takeout Box
🦪 Oyster
🍦 Soft Ice Cream
🍧 Shaved Ice
🍨 Ice Cream
🍩 Doughnut
🍪 Cookie
🎂 Birthday Cake
🍰 Shortcake
🧁 Cupcake
🥧 Pie
🍫 Chocolate Bar
🍬 Candy
🍭 Lollipop
🍮 Custard
🍯 Honey Pot
🍼 Baby Bottle
🥛 Glass of Milk
☕ Hot Beverage
🫖 Teapot
🍵 Teacup Without Handle
🍶 Sake
🍾 Bottle with Popping Cork
🍷 Wine Glass
🍸 Cocktail Glass
🍹 Tropical Drink
🍺 Beer Mug
🍻 Clinking Beer Mugs
🥂 Clinking Glasses
🥃 Tumbler Glass
🫗 Pouring Liquid
🥤 Cup with Straw
🧋 Bubble Tea
🧃 Beverage Box
🧊 Ice
🍴 Fork and Knife
🍽️ Fork and Knife with Plate
🥄 Spoon
🔪 Kitchen Knife
🫙 Jar
🏺 Amphora
🌍 Globe Showing Europe-Africa
🌎 Globe Showing Americas
🌏 Globe Showing Asia-Australia
🗺️ World Map
🗾 Map of Japan
🧭 Compass
🏔️ Snow-Capped Mountain
⛰️ Mountain
🌋 Volcano
🗻 Mount Fuji
🏠 House
🏡 House with Garden
🏢 Office Building
🏣 Japanese Post Office
🏤 Post Office
🏥 Hospital
🏦 Bank
🏨 Hotel
🏩 Love Hotel
🏪 Convenience Store
🏫 School
🏬 Department Store
🏭 Factory
🏯 Japanese Castle
🏰 Castle
💒 Wedding
🗼 Tokyo Tower
🗽 Statue of Liberty
⛪ Church
🕌 Mosque
🛕 Hindu Temple
🕍 Synagogue
⛩️ Shinto Shrine
🕋 Kaaba
⛲ Fountain
⛺ Tent
🌁 Foggy
🌃 Night with Stars
🏙️ Cityscape
🌄 Sunrise Over Mountains
🌅 Sunrise
🌆 Cityscape at Dusk
🌇 Sunset
🌉 Bridge at Night
🎠 Carousel Horse
🎡 Ferris Wheel
🎢 Roller Coaster
🚂 Locomotive
🚃 Railway Car
🚄 High-Speed Train
🚅 Bullet Train
🚆 Train
🚇 Metro
🚈 Light Rail
🚉 Station
🚊 Tram
🚝 Monorail
🚞 Mountain Railway
🚋 Tram Car
🚌 Bus
🚍 Oncoming Bus
🚎 Trolleybus
🚐 Minibus
🚑 Ambulance
🚒 Fire Engine
🚓 Police Car
🚔 Oncoming Police Car
🚕 Taxi
🚖 Oncoming Taxi
🚗 Automobile
🚘 Oncoming Automobile
🚙 Sport Utility Vehicle
🛻 Pickup Truck
🚚 Delivery Truck
🚛 Articulated Lorry
🚜 Tractor
🏎️ Racing Car
🏍️ Motorcycle
🛵 Motor Scooter
🛴 Kick Scooter
🛹 Skateboard
🛼 Roller Skate
🚲 Bicycle
🛴 Kick Scooter
🚏 Bus Stop
🛣️ Motorway
🛤️ Railway Track
⛽ Fuel Pump
🛞 Wheel
🚨 Police Car Light
🚥 Horizontal Traffic Light
🚦 Vertical Traffic Light
🛑 Stop Sign
🚧 Construction
⚓ Anchor
🛟 Ring Buoy
⛵ Sailboat
🛶 Canoe
🚤 Speedboat
🛳️ Passenger Ship
⛴️ Ferry
🛥️ Motor Boat
🚢 Ship
✈️ Airplane
🛩️ Small Airplane
🛫 Airplane Departure
🛬 Airplane Arrival
🪂 Parachute
💺 Seat
🚁 Helicopter
🚟 Suspension Railway
🚠 Mountain Cableway
🚡 Aerial Tramway
🛰️ Satellite
🚀 Rocket
🛸 Flying Saucer
🌠 Shooting Star
🌌 Milky Way
🎆 Fireworks
🎇 Sparkler
🧨 Firecracker
✨ Sparkles
🎈 Balloon
🎉 Party Popper
🎊 Confetti Ball
🎋 Tanabata Tree
🎍 Pine Decoration
🎎 Japanese Dolls
🎏 Carp Streamer
🎐 Wind Chime
🎑 Moon Viewing Ceremony
🧧 Red Envelope
🎀 Ribbon
🎁 Wrapped Gift
🎗️ Reminder Ribbon
🎟️ Admission Tickets
🎫 Ticket
🎖️ Military Medal
🏆 Trophy
🏅 Sports Medal
🥇 1st Place Medal
🥈 2nd Place Medal
🥉 3rd Place Medal
⚽ Soccer Ball
⚾ Baseball
🥎 Softball
🏀 Basketball
🏐 Volleyball
🏈 American Football
🏉 Rugby Football
🎾 Tennis
🥏 Flying Disc
🎳 Bowling
🏏 Cricket Game
🏑 Field Hockey
🏒 Ice Hockey
🥍 Lacrosse
🏓 Ping Pong
🏸 Badminton
🥊 Boxing Glove
🥋 Martial Arts Uniform
🥅 Goal Net
⛳ Flag in Hole
⛸️ Ice Skate
🎣 Fishing Pole
🤿 Diving Mask
🎽 Running Shirt
🎿 Skis
🛷 Sled
🥌 Curling Stone
🎯 Bullseye
🪀 Yo-Yo
🪁 Kite
🎱 Pool 8 Ball
🔮 Crystal Ball
🪄 Magic Wand
🧿 Nazar Amulet
🪬 Hamsa
🎮 Video Game
🕹️ Joystick
🎰 Slot Machine
🎲 Game Die
🧩 Puzzle Piece
🧸 Teddy Bear
🪅 Piñata
🪩 Mirror Ball
🪆 Nesting Dolls
♠️ Spade Suit
♥️ Heart Suit
♦️ Diamond Suit
♣️ Club Suit
♟️ Chess Pawn
🃏 Joker
🀄 Mahjong Red Dragon
🎴 Flower Playing Cards
🎭 Performing Arts
🖼️ Framed Picture
🎨 Artist Palette
🧵 Thread
🪡 Sewing Needle
🧶 Yarn
🪢 Knot
👓 Glasses
🕶️ Sunglasses
🥽 Goggles
🥼 Lab Coat
🦺 Safety Vest
👔 Necktie
👕 T-Shirt
👖 Jeans
🧣 Scarf
🧤 Gloves
🧥 Coat
🧦 Socks
👗 Dress
👘 Kimono
🥻 Sari
🩱 One-Piece Swimsuit
🩲 Briefs
🩳 Shorts
👙 Bikini
👚 Woman's Clothes
🪭 Folding Hand Fan
👛 Purse
👜 Handbag
👝 Clutch Bag
🛍️ Shopping Bags
🎒 Backpack
🩴 Thong Sandal
👞 Man's Shoe
👟 Running Shoe
🥾 Hiking Boot
🥿 Flat Shoe
👠 High-Heeled Shoe
👡 Woman's Sandal
🩰 Ballet Shoes
👢 Woman's Boot
👑 Crown
👒 Woman's Hat
🎩 Top Hat
🎓 Graduation Cap
🧢 Billed Cap
🪖 Military Helmet
⛑️ Rescue Worker's Helmet
💄 Lipstick
💋 Kiss Mark
💌 Love Letter
💘 Heart with Arrow
💝 Heart with Ribbon
💖 Sparkling Heart
💗 Growing Heart
💓 Beating Heart
💞 Revolving Hearts
💕 Two Hearts
💟 Heart Decoration
❣️ Heart Exclamation
💔 Broken Heart
❤️ Red Heart
🩷 Pink Heart
🧡 Orange Heart
💛 Yellow Heart
💚 Green Heart
💙 Blue Heart
🩵 Light Blue Heart
💜 Purple Heart
🖤 Black Heart
🩶 Grey Heart
🤍 White Heart
🤎 Brown Heart
💯 Hundred Points
💬 Speech Balloon
🗯️ Right Anger Bubble
💭 Thought Balloon
🫧 Bubbles
💤 Zzz
💢 Anger Symbol
💣 Bomb
💥 Collision
💦 Sweat Droplets
💨 Dashing Away
🕳️ Hole
💫 Dizzy
💬 Speech Balloon
👁️‍🗨️ Eye in Speech Bubble
🗨️ Left Speech Bubble
🗯️ Right Anger Bubble
💭 Thought Balloon
🫧 Bubbles
💤 Zzz
💢 Anger Symbol
💣 Bomb
💥 Collision
💦 Sweat Droplets
💨 Dashing Away
🕳️ Hole
💫 Dizzy
💬 Speech Balloon
👁️‍🗨️ Eye in Speech Bubble
🗨️ Left Speech Bubble
🗯️ Right Anger Bubble
💭 Thought Balloon
🫧 Bubbles
☀️ Sun
☁️ Cloud
⛅ Sun Behind Cloud
⛈️ Cloud with Lightning and Rain
🌤️ Sun Behind Small Cloud
🌥️ Sun Behind Large Cloud
🌦️ Sun Behind Rain Cloud
🌧️ Cloud with Rain
🌨️ Cloud with Snow
🌩️ Cloud with Lightning
🌪️ Tornado
🌫️ Fog
🌬️ Wind Face
🌀 Cyclone
🌈 Rainbow
🌂 Closed Umbrella
☂️ Umbrella
☔ Umbrella with Rain Drops
⛱️ Umbrella on Ground
⚡ High Voltage
❄️ Snowflake
☃️ Snowman
⛄ Snowman Without Snow
☄️ Comet
🔥 Fire
💧 Droplet
🌊 Water Wave
🎄 Christmas Tree
🎃 Jack-O-Lantern
🕯️ Candle
🧯 Fire Extinguisher
🪔 Diya Lamp
🗿 Moai
🪧 Placard
🪪 Identification Card
📿 Prayer Beads
💈 Barber Pole
⚖️ Balance Scale
🦯 White Cane
🔗 Link
⛓️ Chains
🪝 Hook
🧰 Toolbox
🧲 Magnet
🪜 Ladder
⚗️ Alembic
🧪 Test Tube
🧫 Petri Dish
🧬 DNA
🩸 Drop of Blood
🩹 Adhesive Bandage
🩼 Crutch
🩺 Stethoscope
🪞 Mirror
🪟 Window
🛏️ Bed
🛋️ Couch and Lamp
🪑 Chair
🚪 Door
🛗 Elevator
🪞 Mirror
🪟 Window
🛏️ Bed
🛋️ Couch and Lamp
🪑 Chair
🚪 Door
🛗 Elevator
🚽 Toilet
🚿 Shower
🛁 Bathtub
🪤 Mouse Trap
🪒 Razor
🧴 Lotion Bottle
🧷 Safety Pin
🧹 Broom
🧺 Basket
🧻 Roll of Paper
🪣 Bucket
🧼 Soap
🫧 Bubbles
🧽 Sponge
🧯 Fire Extinguisher
🪥 Toothbrush
🪦 Headstone
🏛️ Classical Building
🪩 Mirror Ball
🪪 Identification Card
🛗 Elevator
EOF
}

choice="$(emojis | rofi -dmenu -i -p "Emoji" -no-custom -theme "$THEME" \
    -theme-str 'entry { placeholder: "Buscar emoji..."; }')" || exit 0
emoji="${choice%% *}"
[[ -n "$emoji" ]] || exit 0

if [[ -n "${WAYLAND_DISPLAY:-}" ]] && command -v wl-copy >/dev/null; then
    printf '%s' "$emoji" | wl-copy
else
    printf '%s' "$emoji" | xclip -selection clipboard
fi
notify-send "Emoji copiado" "$emoji" -t 1000
