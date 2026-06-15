"""
World Cup 2026 — Squad Data Importer
=====================================
Imports all 48 teams × ~26 players (≈1,248 total) into the Players table.
Data sourced from sportshistori.com (squads finalised 2026-06-02).

Idempotent — ON CONFLICT(team_id, name_en) DO UPDATE preserves
existing tournament_goals / tournament_assists / profile_url.
"""

import sqlite3
import logging
import sys
import os
from contextlib import closing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "worldcup2026.db")

# ── Team name mapping (sportshistori → DB Teams.name) ────────────────────
TEAM_NAME_MAP = {
    "Republic of Korea": "South Korea",
    "Czechia": "Czech Republic",
    "United States of America": "United States",
    "T\u00fcrkiye": "Turkey",
    "C\u00f4te d'Ivoire": "Ivory Coast",
    "Islamic Republic of Iran": "Iran",
    "Cabo Verde": "Cape Verde",
    "DR Congo": "Democratic Republic of the Congo",
}

# ── Well-known player Chinese names ───────────────────────────────────────
STAR_ZH = {
    # Argentina
    "Lionel Messi": "利昂内尔·梅西",
    "Emiliano Martínez": "埃米利亚诺·马丁内斯",
    "Lautaro Martínez": "劳塔罗·马丁内斯",
    "Julián Álvarez": "胡利安·阿尔瓦雷斯",
    "Enzo Fernández": "恩佐·费尔南德斯",
    "Rodrigo De Paul": "罗德里戈·德保罗",
    "Ángel Di María": "安赫尔·迪马利亚",
    # Brazil
    "Alisson": "阿利松",
    "Ederson": "埃德森",
    "Marquinhos": "马尔基尼奥斯",
    "Neymar": "内马尔",
    "Vinícius Júnior": "维尼修斯·儒尼奥尔",
    "Raphinha": "拉菲尼亚",
    "Gabriel Martinelli": "加布里埃尔·马丁内利",
    "Casemiro": "卡塞米罗",
    "Bruno Guimarães": "布鲁诺·吉马良斯",
    # France
    "Kylian Mbappé": "基利安·姆巴佩",
    "Ousmane Dembélé": "奥斯曼·登贝莱",
    "N'Golo Kanté": "恩戈洛·坎特",
    "Mike Maignan": "迈克·迈尼昂",
    "William Saliba": "威廉·萨利巴",
    "Dayot Upamecano": "达约·于帕梅卡诺",
    # England
    "Harry Kane": "哈里·凯恩",
    "Jude Bellingham": "裘德·贝林厄姆",
    "Bukayo Saka": "布卡约·萨卡",
    "Declan Rice": "德克兰·赖斯",
    "Phil Foden": "菲尔·福登",
    "John Stones": "约翰·斯通斯",
    # Germany
    "Manuel Neuer": "曼努埃尔·诺伊尔",
    "Joshua Kimmich": "约书亚·基米希",
    "Jamal Musiala": "贾马尔·穆西亚拉",
    "Florian Wirtz": "弗洛里安·维尔茨",
    "Kai Havertz": "凯·哈弗茨",
    "Leroy Sané": "勒鲁瓦·萨内",
    "Antonio Rüdiger": "安东尼奥·吕迪格",
    # Spain
    "Pedri": "佩德里",
    "Gavi": "加维",
    "Rodri": "罗德里",
    "Lamine Yamal": "拉明·亚马尔",
    "Dani Olmo": "达尼·奥尔莫",
    "Nico Williams": "尼科·威廉姆斯",
    # Portugal
    "Cristiano Ronaldo": "克里斯蒂亚诺·罗纳尔多",
    "Bruno Fernandes": "布鲁诺·费尔南德斯",
    "Bernardo Silva": "贝尔纳多·席尔瓦",
    "Rúben Dias": "鲁本·迪亚斯",
    "Rafael Leão": "拉斐尔·莱昂",
    "João Félix": "若昂·费利克斯",
    # Netherlands
    "Virgil van Dijk": "维吉尔·范迪克",
    "Memphis Depay": "孟菲斯·德佩",
    "Cody Gakpo": "科迪·加克波",
    "Frenkie de Jong": "弗伦基·德容",
    # Belgium
    "Kevin De Bruyne": "凯文·德布劳内",
    "Romelu Lukaku": "罗梅卢·卢卡库",
    "Thibaut Courtois": "蒂博·库尔图瓦",
    "Jeremy Doku": "热雷米·多库",
    # Croatia
    "Luka Modric": "卢卡·莫德里奇",
    "Mateo Kovacic": "马特奥·科瓦契奇",
    "Josko Gvardiol": "约什科·格瓦迪奥尔",
    # Uruguay
    "Darwin Núñez": "达尔文·努涅斯",
    "Federico Valverde": "费德里科·巴尔韦德",
    "Ronald Araujo": "罗纳德·阿劳霍",
    # Morocco
    "Achraf Hakimi": "阿什拉夫·哈基米",
    "Yassine Bounou": "亚辛·布努",
    "Brahim Díaz": "卜拉欣·迪亚斯",
    # USA
    "Christian Pulisic": "克里斯蒂安·普利西奇",
    "Weston McKennie": "韦斯顿·麦肯尼",
    "Gio Reyna": "吉奥·雷纳",
    # Norway
    "Erling Haaland": "埃尔林·哈兰德",
    "Martin Ødegaard": "马丁·厄德高",
    # Egypt
    "Mohamed Salah": "穆罕默德·萨拉赫",
    # South Korea
    "Son Heungmin": "孙兴慜",
    "Hwang Heechan": "黄喜灿",
    "Kim Minjae": "金玟哉",
    "Lee Kangin": "李刚仁",
    # Japan
    "Takefusa Kubo": "久保建英",
    "Wataru Endo": "远藤航",
    "Takehiro Tomiyasu": "富安健洋",
    "Ritsu Doan": "堂安律",
    "Daichi Kamada": "镰田大地",
    # Canada
    "Alphonso Davies": "阿方索·戴维斯",
    "Jonathan David": "乔纳森·戴维",
    # Senegal
    "Sadio Mané": "萨迪奥·马内",
    "Kalidou Koulibaly": "卡利杜·库利巴利",
    # Other stars
    "Viktor Gyökeres": "维克托·哲凯赖什",
    "Alexander Isak": "亚历山大·伊萨克",
    "Edin Džeko": "埃丁·哲科",
    "James Rodríguez": "哈梅斯·罗德里格斯",
    "Luis Díaz": "路易斯·迪亚斯",
    "Manuel Akanji": "曼努埃尔·阿坎吉",
    "Granit Xhaka": "格拉尼特·扎卡",
    "Dominik Livakovic": "多米尼克·利瓦科维奇",
    "Mehdi Taremi": "迈赫迪·塔雷米",
    "Almoez Ali": "阿尔莫埃斯·阿里",
    "Akram Afif": "阿克拉姆·阿菲夫",
    "Salem Al Dawsari": "萨勒姆·达瓦萨里",
    "Guillermo Ochoa": "吉列尔莫·奥乔亚",
    "Santiago Gimenez": "圣地亚哥·希门尼斯",
    "Christian Romero": "克里斯蒂安·罗梅罗",
    "Lisandro Martínez": "利桑德罗·马丁内斯",
    "Nicolás Otamendi": "尼古拉斯·奥塔门迪",
    "Alexis Mac Allister": "亚历克西斯·麦卡利斯特",
}

# ── ALL 48 TEAMS SQUAD DATA ──────────────────────────────────────────────
# { sportshistori_team_name: { "<position_group>": ["Player Name", ...], ... } }
SQUADS = {
    # ── GROUP A ───────────────────────────────────────────────────────────
    "Mexico": {
        "GK": ["Raul Rangel", "Carlos Acevedo", "Guillermo Ochoa"],
        "DF": ["Israel Reyes", "Jesús Gallardo", "Jorge Sánchez", "César Montes", "Johan Vásquez", "Mateo Chávez"],
        "MF": ["Erik Lira", "Luis Romo", "Obed Vargas", "Brian Gutiérrez", "Orbelín Pineda", "Edson Álvarez", "Gilberto Mora", "César Huerta", "Álvaro Fidalgo", "Luis Chávez"],
        "FW": ["Roberto Alvarado", "Alexis Vega", "Julián Quiñones", "Santiago Gimenez", "Guillermo Martínez", "Armando González", "Raúl Jiménez"],
    },
    "South Africa": {
        "GK": ["Ronwen Williams", "Ricardo Goss", "Sipho Chaine"],
        "DF": ["Khuliso Mudau", "Olwethu Makhanya", "Bradley Cross", "Thabang Matuludi", "Nkosinathi Sibisi", "Aubrey Modiba", "Khulumani Ndamane", "Ime Okon", "Samukele Kabini", "Mbekezeli Mbokazi"],
        "MF": ["Teboho Mokoena", "Jayden Adams", "Thalente Mbatha", "Kamogelo Sebelebele", "Sphephelo Sithole"],
        "FW": ["Oswin Appollis", "Tshepang Moremi", "Evidence Makgopa", "Lyle Foster", "Iqraam Rayners", "Relebohile Mofokeng", "Themba Zwane", "Thapelo Maseko"],
    },
    "Republic of Korea": {
        "GK": ["Song Bumkeun", "Jo Hyeonwoo", "Kim Seung-gyu"],
        "DF": ["Jens Castrop", "Lee Hanbeom", "Park Jinseob", "Lee Kihyuk", "Kim Minjae", "Kim Moonhwan", "Kim Taehyeon", "Lee Taeseok", "Seol Youngwoo", "Cho Wije"],
        "MF": ["Lee Donggyeong", "Hwang Heechan", "Yang Hyunjun", "Hwang Inbeom", "Lee Jaesung", "Kim Jingyu", "Eom Jisung", "Bae Junho", "Lee Kangin", "Paik Seungho"],
        "FW": ["Cho Guesung", "Son Heungmin", "Oh Hyeongyu"],
    },
    "Czechia": {
        "GK": ["Lukas Hornicek", "Matej Kovar", "Jindrich Stanek"],
        "DF": ["Vladimir Coufal", "David Doudera", "Tomas Holes", "Robin Hranac", "Stepan Chaloupek", "David Jurasek", "Ladislav Krejci", "Jaroslav Zeleny", "David Zima"],
        "MF": ["Lukas Cerv", "Vladimir Darida", "Lukas Provod", "Michal Sadilek", "Hugo Sochurek", "Alexandr Sojka", "Tomas Soucek", "Pavel Sulc", "Denis Visinsky"],
        "FW": ["Adam Hlozek", "Tomas Chory", "Mojmir Chytil", "Jan Kuchta", "Patrik Schick"],
    },
    # ── GROUP B ───────────────────────────────────────────────────────────
    "Canada": {
        "GK": ["Dayne St. Clair", "Maxime Crépeau", "Owen Goodman"],
        "DF": ["Alistair Johnson", "Derek Cornelius", "Richie Laryea", "Niko Sigur", "Joel Waterman", "Luc De Fougerolles", "Moïse Bombito", "Alphonso Davies", "Alfie Jones"],
        "MF": ["Stephen Eustáquio", "Ismaël Koné", "Tajon Buchanan", "Mathieu Choinière", "Ali Ahmed", "Nathan Saliba", "Liam Miller", "Marcelo Flores", "Jacob Shaffelburg", "Jonathan Osorio"],
        "FW": ["Jonathan David", "Cyle Larin", "Tani Oluwaseyi", "Promise David"],
    },
    "Bosnia and Herzegovina": {
        "GK": ["Nikola Vasilj", "Martin Zlomislić", "Osman Hadžikić"],
        "DF": ["Sead Kolašinac", "Amar Dedić", "Nihad Mujakić", "Nikola Katić", "Tarik Muharemović", "Stjepan Radeljić", "Dennis Hadžikadunić", "Nidal Čelik"],
        "MF": ["Amir Hadžiahmetović", "Ivan Šunjić", "Ivan Bašić", "Dženis Burnić", "Ermin Mahmić", "Benjamin Tahirović", "Amar Memić", "Armin Gigović"],
        "FW": ["Kerim Alajbegović", "Esmir Bajraktarević", "Ermedin Demirović", "Jovo Lukić", "Samed Baždar", "Haris Tabaković", "Edin Džeko"],
    },
    "Qatar": {
        "GK": ["Salah Zakaria", "Mahmoud Abunada", "Meshaal Barsham"],
        "DF": ["Hashmi Hussein", "Ayoub Alawi", "Boualem Khoukhi", "Pedro Miguel", "Issa Laaye", "Lucas Mendes", "Sultan Al-Brake", "Homam Al-Amin"],
        "MF": ["Mohammed Al-Manai", "Jassem Jaber", "Karim Boudiaf", "Ahmed Fathi", "Abdulaziz Hatem", "Assim Madibo"],
        "FW": ["Tahseen Mohammed", "Edmilson Junior", "Almoez Ali", "Akram Afif", "Mohammed Muntari", "Youssef Abdulrazzaq", "Ahmed Alaa", "Hassan Al-Haydos", "Ahmed Al-Janahi"],
    },
    "Switzerland": {
        "GK": ["Marvin Keller", "Gregor Kobel", "Yvon Mvogo"],
        "DF": ["Manuel Akanji", "Aurèle Amenda", "Eray Cömert", "Nico Elvedi", "Luca Jaquez", "Miro Muheim", "Ricardo Rodríguez", "Silvan Widmer"],
        "MF": ["Michel Aebischer", "Remo Freuler", "Ardon Jashari", "Fabian Rieder", "Djibril Sow", "Granit Xhaka", "Denis Zakaria"],
        "FW": ["Zeki Amdouni", "Breel Embolo", "Dan Ndoye", "Noah Okafor", "Rubén Vargas", "Christian Fassnacht", "Cedric Itten", "Johan Manzambi"],
    },
    # ── GROUP C ───────────────────────────────────────────────────────────
    "Brazil": {
        "GK": ["Alisson", "Ederson", "Weverton"],
        "DF": ["Wesley", "Douglas Santos", "Alex Sandro", "Gabriel Magalhães", "Marquinhos", "Danilo", "Bremer", "Ibañez", "Léo Pereira"],
        "MF": ["Bruno Guimarães", "Casemiro", "Danilo Santos", "Fabinho", "Lucas Paquetá", "Raphinha", "Neymar"],
        "FW": ["Vinícius Júnior", "Luiz Henrique", "Matheus Cunha", "Gabriel Martinelli", "Igor Thiago", "Endrick", "Rayan"],
    },
    "Morocco": {
        "GK": ["Yassine Bounou", "Munir El Kajoui", "Ahmed Reda Tagnaouti"],
        "DF": ["Noussair Mazraoui", "Anass Salah-Eddine", "Youssef Belammari", "Nayef Aguerd", "Chadi Riad", "Issa Diop", "Redouane Halhal", "Achraf Hakimi", "Zakaria El Ouahdi"],
        "MF": ["Samir El Mourabet", "Ayyoub Bouaddi", "Neil El Aynaoui", "Sofyan Amrabat", "Azzedine Ounahi", "Bilal El Khannouss", "Ismael Saibari"],
        "FW": ["Abdessamad Ezzalzouli", "Chemsdine Talbi", "Soufiane Rahimi", "Ayoub El Kaabi", "Brahim Díaz", "Yassine Gessime", "Ayoube Amaimouni"],
    },
    "Haiti": {
        "GK": ["Johnny Placide", "Alexandre Pierre", "Josué Duverger"],
        "DF": ["Carlens Arcus", "Wilguens Paugain", "Duke Lacroix", "Martin Experience", "Jean-Kevin Duverne", "Ricardo Adé", "Hannes Delcroix", "Keeto Thermoncy"],
        "MF": ["Leverton Pierre", "Carl-Fred Sainthe", "Jean-Jacques Danley", "Jeanricner Bellegarde", "Pierre Woodenski", "Dominique Simon"],
        "FW": ["Louicius Deedson", "Ruben Providence", "Josué Casimir", "Derrick Etienne", "Wilson Isidor", "Duckens Nazon", "Frantzdy Pierrot", "Yassin Fortune", "Lenny Joseph"],
    },
    "Scotland": {
        "GK": ["Craig Gordon", "Angus Gunn", "Liam Kelly"],
        "DF": ["Grant Hanley", "Jack Hendry", "Aaron Hickey", "Dom Hyam", "Scott McKenna", "Nathan Patterson", "Anthony Ralston", "Andy Robertson", "John Souttar", "Kieran Tierney"],
        "MF": ["Ryan Christie", "Findlay Curtis", "Lewis Ferguson", "Ben Gannon-Doak", "Tyler Fletcher", "John McGinn", "Kenny McLean", "Scott McTominay"],
        "FW": ["Ché Adams", "Lyndon Dykes", "George Hirst", "Lawrence Shankland", "Ross Stewart"],
    },
    # ── GROUP D ───────────────────────────────────────────────────────────
    "United States of America": {
        "GK": ["Chris Brady", "Matt Freese", "Matt Turner"],
        "DF": ["Max Arfsten", "Sergiño Dest", "Alex Freeman", "Mark McKenzie", "Tim Ream", "Chris Richards", "Antonee Robinson", "Miles Robinson", "Joe Scally", "Auston Trusty"],
        "MF": ["Tyler Adams", "Sebastian Berhalter", "Weston McKennie", "Gio Reyna", "Cristian Roldan", "Malik Tillman"],
        "FW": ["Brenden Aaronson", "Folarin Balogun", "Ricardo Pepi", "Christian Pulisic", "Tim Weah", "Haji Wright", "Alejandro Zendejas"],
    },
    "Paraguay": {
        "GK": ["Gatito Fernández", "Orlando Gill", "Gastón Olveira"],
        "DF": ["Gustavo Gómez", "Júnior Alonso", "Fabián Balbuena", "Omar Alderete", "Juan José Cáceres", "Gustavo Velázquez", "José Canale", "Alexandro Maidana"],
        "MF": ["Miguel Almirón", "Kaku", "Andrés Cubas", "Ramón Sosa", "Diego Gómez", "Damián Bobadilla", "Braian Ojeda", "Matías Galarza", "Maurício"],
        "FW": ["Antonio Sanabria", "Julio Enciso", "Gabriel Ávalos", "Álex Arce", "Isidro Pitta", "Gustavo Caballero"],
    },
    "Australia": {
        "GK": ["Mathew Ryan", "Paul Izzo", "Tom Glover"],
        "DF": ["Aziz Behich", "Jordan Bos", "Harry Souttar", "Alessandro Circati", "Milos Degenek", "Jason Geria", "Nathaniel Atkinson", "Fran Karacic", "Joel King", "Kye Rowles"],
        "MF": ["Cameron Devlin", "Ajdin Hrustic", "Jackson Irvine", "Connor Metcalfe", "Aiden O'Neill"],
        "FW": ["Nestory Irankunda", "Mathew Leckie", "Marco Tilio", "Kusini Yengi", "Riley McGree", "Christian Volpato"],
    },
    "Türkiye": {
        "GK": ["Altay Bayındır", "Mert Günok", "Uğurcan Çakır"],
        "DF": ["Abdülkerim Bardakcı", "Çağlar Söyüncü", "Eren Elmalı", "Ferdi Kadıoğlu", "Merih Demiral", "Mert Müldür", "Ozan Kabak", "Samet Akaydın", "Zeki Çelik"],
        "MF": ["Hakan Çalhanoğlu", "İsmail Yüksek", "Kaan Ayhan", "Orkun Kökçü", "Salih Özcan"],
        "FW": ["Arda Güler", "Barış Alper Yılmaz", "Can Uzun", "Deniz Gül", "İrfan Can Kahveci", "Kenan Yıldız", "Kerem Aktürkoğlu", "Oğuz Aydın", "Yunus Akgün"],
    },
    # ── GROUP E ───────────────────────────────────────────────────────────
    "Germany": {
        "GK": ["Oliver Baumann", "Manuel Neuer", "Alexander Nübel"],
        "DF": ["Waldemar Anton", "Nathaniel Brown", "Joshua Kimmich", "David Raum", "Antonio Rüdiger", "Nico Schlotterbeck", "Jonathan Tah", "Malick Thiaw"],
        "MF": ["Nadiem Amiri", "Leon Goretzka", "Pascal Groß", "Jamie Leweling", "Lennart Karl", "Jamal Musiala", "Felix Nmecha", "Aleksandar Pavlović", "Angelo Stiller", "Florian Wirtz"],
        "FW": ["Maximilian Beier", "Kai Havertz", "Leroy Sané", "Denis Undav", "Nick Woltemade"],
    },
    "Curaçao": {
        "GK": ["Tyrick Bodak", "Trevor Doornbusch", "Eloy Room"],
        "DF": ["Riechedly Bazoer", "Joshua Brenet", "Roshon Van Eijma", "Sherel Floranus", "Deveron Fonville", "Juriën Gaari", "Armando Obispo", "Shurandy Sambo"],
        "MF": ["Juninho Bacuna", "Leandro Bacuna", "Livano Comenencia", "Kevin Felida", "Ar'Jany Martha", "Tyrese Noslin", "Godfried Roemeratoe"],
        "FW": ["Jeremy Antonisse", "Tahith Chong", "Kenji Gorré", "Sontje Hansen", "Gervane Kastaneer", "Brandley Kuwas", "Jürgen Locadia", "Jearl Margaritha"],
    },
    "Côte d'Ivoire": {
        "GK": ["Yahia Fofana", "Mohamed Koné", "Alban Lafont"],
        "DF": ["Emmanuel Agbadou", "Clément Akpa", "Ousmane Diomandé", "Guéla Doué", "Ghislain Konan", "Odilon Kossounou", "Evan Ndicka", "Wilfried Singo"],
        "MF": ["Seko Fofana", "Parfait Guiagon", "Christ Inao Oulaï", "Franck Kessié", "Ibrahim Sangaré", "Jean-Michaël Seri"],
        "FW": ["Simon Adingra", "Ange-Yoan Bonny", "Amad Diallo", "Oumar Diakité", "Yan Diomandé", "Evann Guessand", "Nicolas Pépé", "Bazoumana Touré", "Elye Wahi"],
    },
    "Ecuador": {
        "GK": ["Hernán Galíndez", "Moisés Ramírez", "Gonzalo Valle"],
        "DF": ["Willian Pacho", "Piero Hincapié", "Joel Ordóñez", "Félix Torres", "Pervis Estupiñán", "Ángelo Preciado", "Jackson Porozo"],
        "MF": ["Moisés Caicedo", "Jordy Alcívar", "Denil Castillo", "Alan Franco", "Pedro Vite", "Kendry Páez", "Yaimar Medina"],
        "FW": ["Kevin Rodríguez", "Anthony Valencia", "Enner Valencia", "Jordy Caicedo", "Jeremy Arévalo", "Gonzalo Plata", "Alan Minda", "John Yeboah", "Nilson Angulo"],
    },
    # ── GROUP F ───────────────────────────────────────────────────────────
    "Netherlands": {
        "GK": ["Mark Flekken", "Robin Roefs", "Bart Verbruggen"],
        "DF": ["Nathan Aké", "Denzel Dumfries", "Jorrel Hato", "Jurriën Timber", "Micky van de Ven", "Virgil van Dijk", "Jan Paul van Hecke", "Mats Wieffer"],
        "MF": ["Frenkie de Jong", "Marten de Roon", "Ryan Gravenberch", "Justin Kluivert", "Teun Koopmeiners", "Tijjani Reijnders", "Guus Til", "Quinten Timber"],
        "FW": ["Brian Brobbey", "Memphis Depay", "Cody Gakpo", "Noa Lang", "Donyell Malen", "Crysencio Summerville", "Wout Weghorst"],
    },
    "Japan": {
        "GK": ["Tomoki Hayakawa", "Zion Suzuki", "Keisuke Osako"],
        "DF": ["Yuto Nagatomo", "Shogo Taniguchi", "Takehiro Tomiyasu", "Ko Itakura", "Tsuyoshi Watanabe", "Hiroki Ito", "Junnosuke Suzuki", "Ayumu Seko", "Yukinari Sugawara"],
        "MF": ["Daichi Kamada", "Kaishu Sano", "Ao Tanaka", "Wataru Endo", "Keito Nakamura", "Ritsu Doan", "Junya Ito", "Takefusa Kubo", "Yuito Suzuki"],
        "FW": ["Ayase Ueda", "Koki Ogawa", "Daizen Maeda", "Kento Shiogai", "Keisuke Goto"],
    },
    "Sweden": {
        "GK": ["Viktor Johansson", "Kristoffer Nordfeldt", "Jacob Widell Zetterström"],
        "DF": ["Hjalmar Ekdal", "Gabriel Gudmundsson", "Isak Hien", "Gustaf Lagerbielke", "Victor Lindelöf", "Eric Smith", "Carl Starfelt", "Elliot Stroud", "Daniel Svensson"],
        "MF": ["Jesper Karlström", "Yasin Ayari", "Mattias Svanberg", "Lucas Bergvall", "Besfort Zeneli", "Herman Johansson"],
        "FW": ["Taha Ali", "Alexander Bernhardsson", "Anthony Elanga", "Viktor Gyökeres", "Alexander Isak", "Gustaf Nilsson", "Benjamin Nygren", "Ken Sema"],
    },
    "Tunisia": {
        "GK": ["Sabri Ben Hassan", "Abdelmouhib Chamakh", "Aymen Dahmen"],
        "DF": ["Ali Abdi", "Adem Arous", "Mohamed Amine Ben Hamida", "Dylan Bronn", "Raed Chikhaoui", "Moutaz Neffati", "Omar Rekik", "Montassar Talbi", "Yan Valery"],
        "MF": ["Mortadha Ben Ouanes", "Anis Ben Slimane", "Ismael Gharbi", "Rani Khedira", "Mohamed Hadj Mahmoud", "Hannibal Mejbri", "Ellyes Skhiri"],
        "FW": ["Elias Achouri", "Khalil Ayari", "Firas Chaouat", "Rayan Elloumi", "Hazem Mastouri", "Elias Saad", "Sebastian Tounekti"],
    },
    # ── GROUP G ───────────────────────────────────────────────────────────
    "Belgium": {
        "GK": ["Thibaut Courtois", "Senne Lammens", "Mike Penders"],
        "DF": ["Timothy Castagne", "Zeno Debast", "Maxim De Cuyper", "Koni De Winter", "Brandon Mechele", "Thomas Meunier", "Nathan Ngoy", "Joaquin Seys", "Arthur Theate"],
        "MF": ["Kevin De Bruyne", "Amadou Onana", "Nicolas Raskin", "Youri Tielemans", "Hans Vanaken", "Axel Witsel"],
        "FW": ["Charles De Ketelaere", "Jeremy Doku", "Matias Fernandez Pardo", "Romelu Lukaku", "Dodi Lukebakio", "Diego Moreira", "Alexis Saelemaekers", "Leandro Trossard"],
    },
    "Egypt": {
        "GK": ["Mohamed El Shenawy", "Mostafa Shobeir", "Mohamed Alaa"],
        "DF": ["Mohamed Hani", "Tarek Alaa", "Hamdy Fathy", "Rami Rabia", "Yasser Ibrahim", "Hossam Abdelmaguid", "Mohamed Abdelmonem", "Ahmed Fotouh", "Karim Hafez"],
        "MF": ["Marwan Attia", "Mohanad Lasheen", "Nabil Emad", "Mahmoud Saber", "Ahmed Zizo", "Emam Ashour", "Mostafa Ziko", "Mahmoud Trezeguet", "Ibrahim Adel", "Haissem Hassan"],
        "FW": ["Mohamed Salah", "Omar Marmoush", "Aqtay Abdallah", "Hamza Abdelkarim"],
    },
    "Islamic Republic of Iran": {
        "GK": ["Alireza Beiranvand", "Seyed Hossein Hosseini", "Payam Niazmand"],
        "DF": ["Danial Eiri", "Ehsan Hajsafi", "Saleh Hardani", "Hossein Kanaani", "Shoja Khalilzadeh", "Milad Mohammadi", "Ali Nemati", "Omid Noorafkan", "Ramin Rezaeian"],
        "MF": ["Rouzbeh Cheshmi", "Saeid Ezatolahi", "Mehdi Ghaedi", "Saman Ghoddos", "Mohammad Ghorbani", "Alireza Jahanbakhsh", "Mohammad Mohebi", "Amir Mohammad Razzaghinia", "Mehdi Torabi", "Aria Yousefi"],
        "FW": ["Ali Alipour", "Dennis Dargahi", "Amirhossein Hosseinzadeh", "Mehdi Taremi", "Shahriyar Moghanlou"],
    },
    "New Zealand": {
        "GK": ["Max Crocombe", "Alex Paulsen", "Michael Woud"],
        "DF": ["Tim Payne", "Francis De Vries", "Tyler Bindon", "Michael Boxall", "Liberato Cacace", "Nando Pijnaker", "Finn Surman", "Callan Elliot", "Tommy Smith"],
        "MF": ["Joe Bell", "Marko Stamenić", "Alex Rufer", "Ryan Thomas", "Lachlan Bayliss"],
        "FW": ["Matt Garbett", "Chris Wood", "Sarpreet Singh", "Eli Just", "Kosta Barbarouses", "Ben Waine", "Ben Old", "Callum McCowatt", "Jesse Randall"],
    },
    # ── GROUP H ───────────────────────────────────────────────────────────
    "Spain": {
        "GK": ["Unai Simón", "David Raya", "Joan Garcia"],
        "DF": ["Marc Cucurella", "Alejandro Grimaldo", "Pau Cubarsí", "Aymeric Laporte", "Marc Pubill", "Eric García", "Marcos Llorente", "Pedro Porro"],
        "MF": ["Pedri", "Fabián Ruiz", "Martín Zubimendi", "Gavi", "Rodri", "Álex Baena", "Mikel Merino"],
        "FW": ["Mikel Oyarzabal", "Dani Olmo", "Nico Williams", "Yéremy Pino", "Ferran Torres", "Borja Iglesias", "Víctor Muñoz", "Lamine Yamal"],
    },
    "Cabo Verde": {
        "GK": ['Josimar Dias "Vozinha"', "Márcio da Rosa", "Carlos Santos"],
        "DF": ["Steven Moreira", "Wagner Pina", "João Paulo Fernandes", "Sidny Lopes Cabral", "Logan Costa", 'Roberto Lopes "Pico"', "Kelvin Pires", 'Ianique Tavares "Stopira"', 'Edilson Borges "Diney"'],
        "MF": ["Jamiro Monteiro", "Telmo Arcanjo", "Yannick Semedo", "Laros Duarte", "Deroy Duarte", "Kevin Pina"],
        "FW": ["Ryan Mendes", "Willy Semedo", "Garry Rodrigues", "Jovane Cabral", "Nuno Da Costa", "Dailon Livramento", "Gilson Benchimol", "Hélio Varela"],
    },
    "Saudi Arabia": {
        "GK": ["Nawaf Al Aqidi", "Mohamed Al Owais", "Ahmed Alkassar"],
        "DF": ["Saud Abdulhamid", "Jehad Thakri", "Abdulelah Al Amri", "Hassan Tambakti", "Ali Lajami", "Hassan Kadesh", "Moteb Al Harbi", "Nawaf Boushal", "Ali Majrashi", "Mohammed Abu Alshamat"],
        "MF": ["Ziyad Al Johani", "Nasser Al Dawsari", "Mohamed Kanno", "Abdullah Al Khaibari", "Alaa Al Hejji", "Musab Al Juwayr", "Sultan Mandash", "Ayman Yahya", "Khalid Al Ghannam"],
        "FW": ["Salem Al Dawsari", "Abdullah Al Hamdan", "Feras Al Brikan", "Saleh Al Shehri"],
    },
    "Uruguay": {
        "GK": ["Sergio Rochet", "Fernando Muslera", "Santiago Mele"],
        "DF": ["Guillermo Varela", "Ronald Araujo", "José María Giménez", "Santiago Bueno", "Sebastián Cáceres", "Mathías Olivera", "Joaquín Piquerez", "Matías Viña"],
        "MF": ["Manuel Ugarte", "Emiliano Martínez", "Rodrigo Bentancur", "Federico Valverde", "Agustín Canobbio", "Juan Manuel Sanabria", "Giorgan de Arrascaeta", "Nicolás de la Cruz", "Rodrigo Zalazar", "Facundo Pellistri", "Maximiliano Araújo", "Brian Rodríguez"],
        "FW": ["Rodrigo Aguirre", "Federico Viñas", "Darwin Núñez"],
    },
    # ── GROUP I ───────────────────────────────────────────────────────────
    "France": {
        "GK": ["Mike Maignan", "Brice Samba", "Robin Risser"],
        "DF": ["Dayot Upamecano", "William Saliba", "Lucas Digne", "Theo Hernandez", "Lucas Hernandez", "Ibrahima Konaté", "Jules Koundé", "Malo Gusto", "Maxence Lacroix"],
        "MF": ["N'Golo Kanté", "Adrien Rabiot", "Manu Koné", "Aurélien Tchouaméni", "Warren Zaïre-Emery"],
        "FW": ["Maghnes Akliouche", "Kylian Mbappé", "Ousmane Dembélé", "Michael Olise", "Désiré Doué", "Bradley Barcola", "Rayan Cherki", "Marcus Thuram", "Jean-Philippe Mateta"],
    },
    "Senegal": {
        "GK": ["Édouard Mendy", "Mory Diaw", "Yehvann Diouf"],
        "DF": ["Krépin Diatta", "Antoine Mendy", "Kalidou Koulibaly", "El Hadji Malick Diouf", "Mamadou Sarr", "Moussa Niakhaté", "Abdoulaye Seck", "Ismaïl Jakobs"],
        "MF": ["Idrissa Gana Gueye", "Pape Gueye", "Lamine Camara", "Habib Diarra", "Pathé Ciss", "Pape Matar Sarr", "Bara Sapoko Ndiaye"],
        "FW": ["Sadio Mané", "Ismaïla Sarr", "Iliman Ndiaye", "Assane Diao", "Ibrahim Mbaye", "Nicolas Jackson", "Bamba Dieng", "Chérif Ndiaye"],
    },
    "Iraq": {
        "GK": ["Fahad Talib", "Jalal Hassan", "Ahmed Basil"],
        "DF": ["Hussein Ali", "Manaf Younis", "Zaid Tahseen", "Rebin Sulaka", "Akam Hashem", "Merchas Doski", "Ahmed Yahya", "Zaid Ismail", "Frans Putros", "Mustafa Saadoon"],
        "MF": ["Amir Al-Ammari", "Kevin Yakob", "Zidane Iqbal", "Aimar Sher", "Ibrahim Bayesh", "Ahmed Qasem", "Youssef Amyn", "Marko Farji"],
        "FW": ["Ali Jassim", "Ali Al-Hamadi", "Ali Youssef", "Aymen Hussein", "Mohanad Ali"],
    },
    "Norway": {
        "GK": ["Ørjan Nyland", "Egil Selvik", "Sander Tangvik"],
        "DF": ["Julian Ryerson", "Kristoffer Ajer", "Leo Skiri Østigård", "David Møller Wolfe", "Marcus Holmgren Pedersen", "Torbjørn Heggem", "Fredrik Bjørkan", "Henrik Falchener", "Sondre Langås"],
        "MF": ["Martin Ødegaard", "Sander Berge", "Patrick Berg", "Kristian Thorstvedt", "Morten Thorsby", "Thelo Aasgaard", "Andreas Schjelderup", "Jens Petter Hauge", "Fredrik Aursnes"],
        "FW": ["Erling Haaland", "Alexander Sørloth", "Jørgen Strand Larsen", "Oscar Bobb", "Antonio Nusa"],
    },
    # ── GROUP J ───────────────────────────────────────────────────────────
    "Argentina": {
        "GK": ["Emiliano Martínez", "Gerónimo Rulli", "Juan Musso"],
        "DF": ["Gonzalo Montiel", "Nahuel Molina", "Lisandro Martínez", "Nicolás Otamendi", "Leonardo Balerdi", "Cristian Romero", "Facundo Medina", "Nicolás Tagliafico"],
        "MF": ["Leandro Paredes", "Rodrigo De Paul", "Exequiel Palacios", "Enzo Fernández", "Alexis Mac Allister", "Giovani Lo Celso", "Valentín Barco"],
        "FW": ["Lionel Messi", "Nicolás Paz", "Thiago Almada", "Nicolás González", "Giuliano Simeone", "Lautaro Martínez", "José Manuel López", "Julián Álvarez"],
    },
    "Algeria": {
        "GK": ["Luca Zidane", "Oussama Benbot", "Melvin Mastil"],
        "DF": ["Rafik Belghali", "Samir Chergui", "Rayan Aït-Nouri", "Jaouen Hadjam", "Aïssa Mandi", "Ramy Bensebaïni", "Zinedine Belaïd", "Mohamed Amine Tougaï", "Achraf Abada"],
        "MF": ["Nabil Bentaleb", "Hicham Boudaoui", "Houssem Aouar", "Farès Chaïbi", "Ibrahim Maza", "Yacine Titraoui", "Ramiz Zerrouki"],
        "FW": ["Mohamed Amine Amoura", "Nadhir Benbouali", "Adil Boulbina", "Farès Ghedjemis", "Amine Gouiri", "Anis Hadj Moussa", "Riyad Mahrez"],
    },
    "Austria": {
        "GK": ["Patrick Pentz", "Alexander Schlager", "Florian Wiegele"],
        "DF": ["David Affengruber", "David Alaba", "Kevin Danso", "Marco Friedl", "Philipp Lienhart", "Phillipp Mwene", "Stefan Posch", "Alexander Prass", "Michael Svoboda"],
        "MF": ["Christoph Baumgartner", "Carney Chukwuemeka", "Florian Grillitsch", "Konrad Laimer", "Marcel Sabitzer", "Xaver Schlager", "Nicolas Seiwald", "Romano Schmid", "Alessandro Schöpf", "Paul Wanner", "Patrick Wimmer"],
        "FW": ["Marko Arnautović", "Michael Gregoritsch", "Sasa Kalajdzic"],
    },
    "Jordan": {
        "GK": ["Yazid Abulaila", "Abdallah Al Fakhouri", "Nour Bani Attiah"],
        "DF": ["Mohammad Abualnadi", "Husam Abu Dahab", "Mohammad Abu Hashish", "Yazan Al Arab", "Abdallah Nasib", "Saleem Obaid", "Ehsan Haddad", "Saed Al-Rosan", "Anas Banawi", "Mohannad Abu Taha"],
        "MF": ["Mohammad Al Dawoud", "Nizar Al Rashdan", "Noor Al Rawabdeh", "Rajaei Ayed", "Amer Jamous", "Ibrahim Sadeh", "Mahmoud Al-Mardi"],
        "FW": ["Mousa Al Tamari", "Odeh Al-Fakhouri", "Mohammad Abu Zrayq", "Ali Azaizeh", "Ali Olwan", "Ibrahim Sabra"],
    },
    # ── GROUP K ───────────────────────────────────────────────────────────
    "Portugal": {
        "GK": ["Diogo Costa", "José Sá", "Rui Silva"],
        "DF": ["Diogo Dalot", "Matheus Nunes", "Nélson Semedo", "João Cancelo", "Nuno Mendes", "Gonçalo Inácio", "Renato Veiga", "Rúben Dias", "Tomás Araújo"],
        "MF": ["Rúben Neves", "Samuel Costa", "João Neves", "Vitinha", "Bruno Fernandes", "Bernardo Silva"],
        "FW": ["João Félix", "Francisco Trincão", "Francisco Conceição", "Pedro Neto", "Rafael Leão", "Gonçalo Guedes", "Gonçalo Ramos", "Cristiano Ronaldo"],
    },
    "DR Congo": {
        "GK": ["Timothy Fayulu", "Lionel Mpasi", "Mike Epolo"],
        "DF": ["Aaron Wan-Bissaka", "Gédéon Kalulu", "Joris Kayembe", "Arthur Masuaku", "Steve Kapuadi", "Rocky Bushiri", "Axel Tuanzebe", "Chancel Mbemba", "Dylan Batubinsika"],
        "MF": ["Noah Sadiki", "Samuel Moutoussamy", "Edo Kayembe", "Nathan Mukau", "Charles Pickel", "Ngal'ayel Mukau Mbuku", "Brian Cipenga", "Théo Bongonda", "Gaël Kakuta"],
        "FW": ["Meschack Elia", "Fiston Mayele", "Cédric Bakambu", "Simon Banza", "Yoane Wissa"],
    },
    "Uzbekistan": {
        "GK": ["Utkir Yusupov", "Abduvohid Nematov", "Botirali Ergashev"],
        "DF": ["Rustam Ashurmatov", "Farrukh Sayfiev", "Khojiakbar Alijonov", "Sherzod Nasrullaev", "Umar Eshmurodov", "Abdukodir Khusanov", "Abdulla Abdullaev", "Bekhruz Karimov", "Jakhongir Urozov", "Avazbek Ulmasaliev"],
        "MF": ["Otabek Shukurov", "Jaloliddin Masharipov", "Odiljon Hamrobekov", "Oston Urunov", "Jamshid Iskanderov", "Dostonbek Khamdamov", "Abbosbek Fayzullaev", "Akmal Mozgovoy", "Azizjon Ganiev", "Sherzod Esanov"],
        "FW": ["Eldor Shomurodov", "Igor Sergeev", "Azizbek Amonov"],
    },
    "Colombia": {
        "GK": ["Camilo Vargas", "David Ospina", "Álvaro Montero"],
        "DF": ["Johan Mojica", "Devier Machado", "Daniel Muñoz", "Santiago Arias", "Yerry Mina", "Davinson Sánchez", "Jhon Lucumí", "Willer Ditta"],
        "MF": ["James Rodríguez", "Jefferson Lerma", "Richard Ríos", "Juan Fernando Quintero", "Jorge Carrascal", "Kevin Castaño", "Jaminton Campaz"],
        "FW": ["Luis Díaz", "Carlos Andrés Gómez", "Jhon Córdoba", "Juan Camilo Hernández", "Jhon Arias"],
    },
    # ── GROUP L ───────────────────────────────────────────────────────────
    "England": {
        "GK": ["Jordan Pickford", "Dean Henderson", "James Trafford"],
        "DF": ["Reece James", "Tino Livramento", "Marc Guéhi", "Ezri Konsa", "John Stones", "Jarell Quansah", "Nico O'Reilly", "Dan Burn", "Djed Spence"],
        "MF": ["Declan Rice", "Elliot Anderson", "Jude Bellingham", "Jordan Henderson", "Morgan Rogers", "Kobbie Mainoo", "Eberechi Eze"],
        "FW": ["Harry Kane", "Ivan Toney", "Ollie Watkins", "Bukayo Saka", "Noni Madueke", "Marcus Rashford", "Anthony Gordon"],
    },
    "Croatia": {
        "GK": ["Dominik Livakovic", "Dominik Kotarski", "Ivor Pandur"],
        "DF": ["Josko Gvardiol", "Duje Caleta-Car", "Josip Sutalo", "Josip Stanisic", "Marin Pongracic", "Martin Erlic", "Luka Vuskovic"],
        "MF": ["Luka Modric", "Mateo Kovacic", "Mario Pasalic", "Nikola Vlasic", "Luka Sucic", "Martin Baturina", "Kristijan Jakic", "Petar Sucic", "Nikola Moro", "Toni Fruk"],
        "FW": ["Ivan Perisic", "Andrej Kramaric", "Ante Budimir", "Marco Pasalic", "Petar Musa", "Igor Matanovic"],
    },
    "Ghana": {
        "GK": ["Benjamin Asare", "Lawrence Ati-Zigi", "Joseph Anang"],
        "DF": ["Baba Abdul Rahman", "Derrick Luckassen", "Gideon Mensah", "Marvin Senaya", "Alidu Seidu", "Abdul Mumin", "Jerome Opoku", "Jonas Adjetey", "Kojo Oppong Peprah"],
        "MF": ["Thomas Partey", "Kamaldeen Sulemana", "Kwasi Sibo", "Augustine Boakye", "Caleb Yirenkyi", "Abdul Fatawu Issahaku", "Elisha Owusu"],
        "FW": ["Christopher Bonsu Baah", "Ernest Nuamah", "Antoine Semenyo", "Brandon Thomas-Asante", "Prince Kwabena Adu", "Iñaki Williams", "Jordan Ayew"],
    },
    "Panama": {
        "GK": ["Orlando Mosquera", "Luis Mejía", "César Samudio"],
        "DF": ["César Blackman", "Jorge Gutiérrez", "Amir Murillo", "Fidel Escobar", "Andrés Andrade", "Edgardo Fariña", "José Córdoba", "Eric Davis", "Jiovani Ramos", "Roderick Miller"],
        "MF": ["Aníbal Godoy", "Adalberto Carrasquilla", "Carlos Harvey", "Cristian Martínez", "José Luis Rodríguez", "Cesar Yanis", "Yoel Bárcenas", "Alberto Quintero", "Azarías Londoño"],
        "FW": ["Ismael Díaz", "Cecilio Waterman", "José Fajardo", "Tomás Rodríguez"],
    },
}

# ═══════════════════════════════════════════════════════════════════════════
#  Main import logic
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_db_name(sportshistori_name: str) -> str:
    """Map sportshistori name to DB Teams.name."""
    return TEAM_NAME_MAP.get(sportshistori_name, sportshistori_name)


def import_all(db_path: str = DB_PATH) -> int:
    """Import all 48 teams' squads. Returns total players upserted."""

    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            with closing(conn.cursor()) as cur:
                # Build team lookup: DB name → id, name_zh
                cur.execute("SELECT id, name, name_zh FROM Teams")
                db_team_lookup = {row[1]: (row[0], row[2]) for row in cur.fetchall()}

            inserted = 0
            updated = 0
            skipped_team = 0

            for sh_name, positions in SQUADS.items():
                db_name = _resolve_db_name(sh_name)
                team_info = db_team_lookup.get(db_name)

                if not team_info:
                    logger.warning("Team not in DB: %s (looked for %s)", sh_name, db_name)
                    skipped_team += 1
                    continue

                team_id, team_zh = team_info

                for pos_group, players in positions.items():
                    pos_code = {
                        "GK": "GK", "DF": "DF", "MF": "MF", "FW": "FW",
                    }.get(pos_group, "FW")

                    for name_en in players:
                        name_en = name_en.strip()
                        if not name_en:
                            continue

                        name_zh = STAR_ZH.get(name_en, name_en)

                        with closing(conn.cursor()) as cur:
                            cur.execute(
                                "SELECT id, tournament_goals, tournament_assists, profile_url FROM Players WHERE team_id = ? AND name_en = ?",
                                (team_id, name_en),
                            )
                            existing = cur.fetchone()

                            if existing:
                                # Update name_zh but preserve goals/assists/avatar
                                cur.execute(
                                    "UPDATE Players SET name_zh = ?, position = ? WHERE id = ?",
                                    (name_zh, pos_code, existing[0]),
                                )
                                updated += 1
                            else:
                                cur.execute(
                                    """INSERT INTO Players
                                       (team_id, name_en, name_zh, position, jersey_number,
                                        profile_url, history_stats, tournament_goals, tournament_assists)
                                       VALUES (?, ?, ?, ?, 0, '#', '{}', 0, 0)""",
                                    (team_id, name_en, name_zh, pos_code),
                                )
                                inserted += 1

            conn.commit()

        logger.info(
            "Squad import complete: %d inserted, %d updated, %d teams skipped.",
            inserted, updated, skipped_team,
        )
        return inserted + updated

    except sqlite3.Error as e:
        logger.error("Database error during squad import: %s", e)
        return 0


if __name__ == "__main__":
    total = import_all()
    if total:
        logger.info("Total players in DB after import: %d+", total)
        sys.exit(0)
    else:
        logger.error("Import failed or produced zero players.")
        sys.exit(1)
