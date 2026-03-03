import json
import os
from time import sleep
from PIL import Image
import numpy as np
from isort.core import process
from scipy.ndimage import gaussian_filter
import argparse
import sys
import threading
from multiprocessing import Process, Queue, Pool, Event # Paralelizacija
import multiprocessing as mp
from sqlalchemy.sql.operators import json_path_getitem_op

# Klasa za čuvanje slika sa podrškom za višestruke niti
class Registar_slika:
    def __init__(self, niz_slika):
        self.niz_slika = niz_slika # lista slika u registru
        self.lock = threading.Lock() # mehanizam za sprecavanje konflikta medju nitima

# Klasa za čuvanje zadataka sa podrškom za višestruke niti
class Registar_zadatak:
    def __init__(self, niz_zadatak):
        self.niz_zadatak = niz_zadatak # lista zadataka
        self.lock = threading.Lock() # mehanizam zakljucavanja

# Globalne promenljive
registar_slika = None
slika_id = 0
zadatak_id = 0
red_za_zadatke = None # red za obradu zadataka
shut_down = None # signal za gasenje

def slika_inkrement():
    global slika_id
    slika_id += 1
    return slika_id

def zadatak_inkrement():
    global zadatak_id
    zadatak_id += 1
    return zadatak_id

class Slika:

    def __init__(self, putanja, ime, zadatak_id, zadaci_lista, delete_flag, tip_filtera, preci):
        self.slika_id = slika_inkrement()
        self.putanja = putanja
        self.ime = ime
        self.zadatak_id = zadatak_id
        self.zadaci_lista = zadaci_lista
        self.delete_flag = delete_flag
        self.tip_filtera = tip_filtera  # Lista filtera primenjenih na sliku
        self.preci = preci # Lista "roditeljskih" slika (za slike koje su generisane)

class  Vrsta_Filtera:
    Grayscale = "Grayscale"
    Gaussian_Blur = "Gaussian Blur"
    Brightness_Adjustment = "Brightness Adjustment"

class Status:
    Cekanje = "Cekanje"
    U_obradi = "U_obradi"
    Zavrseno = "Zavrseno"

class Zadatak:
    def __init__(self, id_original, id_kopija, vrsta_transformacije ):
        self.zadatak_id = zadatak_inkrement()
        self.id_original = id_original
        self.id_kopija = id_kopija
        self.vrsta_transformacije = vrsta_transformacije
        self.status = Status.Cekanje
        self.condition = threading.Condition() # Mehanizam za sinhronizaciju


# Funkcija za dodavanje slike u registar   #kopira sliku u direktorijum ./slike
def dodaj_sliku(path, registar_slika):
    slika = Image.open(path)
    ime_slike = slika.filename.split('\\')[-1]
    new_path = f"slike\\{ime_slike}"
    slika.save(new_path)
    slika_registar = Slika(new_path, ime_slike, 0, [], 0, [],[])
    registar_slika.lock.acquire()
    registar_slika.niz_slika.append(slika_registar)
    registar_slika.lock.release()


#Komanda delete briše sliku. Prilikom brisanja komanda prvo postavlja flag koji
#ozanačva da je slika ozančena za brisanje, pa proverava sve zadatke koji koriste
#tu sliku i čeka da se završe pre brisanja.
def obrisi_sliku(slika_id, registar_slika):   #
    slika_za_brisanje = None
    registar_slika.lock.acquire()
    for slika in registar_slika.niz_slika:
        if int(slika_id) == int(slika.slika_id):
            slika_za_brisanje = slika
    registar_slika.lock.release()
    slika_za_brisanje.delete_flag = 1

    # Čeka dok se ne završe svi zadaci vezani za sliku
    for zadatak in slika.zadaci_lista:
        if zadatak.status != Status.Zavrseno:
            with zadatak.condition:
                zadatak.condition.wait()

    # Ponovo zaključava registar da bi uklonio sliku.
    registar_slika.lock.acquire()
    registar_slika.niz_slika.remove(slika_za_brisanje)
    registar_slika.lock.release()

    os.remove(slika_za_brisanje.putanja) # Briše fajl sa diska.

def opisi_sliku (slika_id, registar_slika, red_za_poruke):
    slika_za_opisivanje = None
    registar_slika.lock.acquire()
    for slika in registar_slika.niz_slika:
        if int(slika_id) == int(slika.slika_id):
            slika_za_opisivanje = slika
    registar_slika.lock.release()

    if slika_za_opisivanje.zadatak_id != 0: # slika nastala iz zadatka
        red_za_poruke.put(slika_za_opisivanje.zadatak_id)  #Dodaje ID zadatka u red.

    registar_slika.lock.acquire()

    # Pronalazi sve "pretke" slike i dodaje njihove informacije u red.
    for slika_id in slika_za_opisivanje.preci:
        for slika in registar_slika.niz_slika:
            if int(slika_id) == int(slika.slika_id): #za pretke
                red_za_poruke.put(f"{slika.ime, slika.zadatak_id}") #njihovi zadaci (dodaje ime i zadatak)
    registar_slika.lock.release()

    if red_za_poruke.empty() == True:
        red_za_poruke.put("Ova slika je original")

# ispisuje sve slike koje se nalaze u registru slika (kao par id slike, putanja do slike)
def izlistaj_slike(registar_slika, red_za_poruke):
    registar_slika.lock.acquire()
    for slika in registar_slika.niz_slika:
        red_za_poruke.put(f"{slika.slika_id}, {slika.putanja}") # Dodaje ID i putanju u red.
    registar_slika.lock.release()

def izadji_komanda(shut_down): #zaustavlja sve aktivne niti i procese
    shut_down.set()  # Postavlja signal za gašenje svih niti i procesa


#Njihov kod
def grayscale(image_array):
    red_channel = image_array[..., 0]
    green_channel = image_array[..., 1]
    blue_channel = image_array[..., 2]

    grayscale_image = (red_channel * 0.299 + green_channel * 0.587 + blue_channel * 0.114)
    return grayscale_image.astype(np.uint8)


def gaussian_blur(image_array, sigma=1):

    red_channel = gaussian_filter(image_array[..., 0], sigma=sigma)
    green_channel = gaussian_filter(image_array[..., 1], sigma=sigma)
    blue_channel = gaussian_filter(image_array[..., 2], sigma=sigma)

    blurred_image = np.zeros_like(image_array)
    blurred_image[..., 0] = red_channel
    blurred_image[..., 1] = green_channel
    blurred_image[..., 2] = blue_channel

    if image_array.shape[-1] == 4:
        alpha_channel = image_array[..., 3]
        blurred_image[..., 3] = alpha_channel

    blurred_image = np.clip(blurred_image, 0, 255)

    return blurred_image.astype(np.uint8)

def adjust_brightness(image_array, factor=1.0):
    mean_intensity = np.mean(image_array, axis=(0, 1), keepdims=True)
    image_array = (image_array - mean_intensity) * factor + mean_intensity

    adjusted_image = np.clip(image_array, 0, 255)
    return adjusted_image.astype(np.uint8)


def load_image(image_path):
    image = Image.open(image_path)
    return np.array(image)
#Kraj njihovog koda


# Globalna promenljiva koja se koristi za čuvanje trenutnog procesa (tip filtera).
proces = None
def load_JSON_file(json_path):
    with open(json_path) as f:
        params = json.load(f)
        print(params)
# Dohvatanje vrednosti ključa "tip_filtera" iz JSON podataka i dodeljivanje globalnoj promenljivoj `proces`
        proces = params.get("tip_filtera")



''' Kada se unese komanda obradi, funkcija process_thread radi sledeće:
-Učitava podatke iz JSON fajla.
-Pronalazi originalnu sliku u registru slika.
-Proverava da li je slika označena za brisanje (ako jeste, prekida obradu).
-Pravi kopiju slike i dodaje novi filter na nju.
-Dodaje zadatak u red zadataka za obradu.   '''
# Funkcija koja obrađuje jednu sliku u zasebnom procesu.
def process_thread(file, registar_slika, registar_zadatak, red_za_poruke, pool):
    # Učitavanje parametara iz prosleđenog JSON fajla.
    with open(file) as f:
        params = json.load(f)
        # Dohvatanje tipa filtera koji treba primeniti.
        proces = params.get("tip_filtera")
    # Određivanje vrste filtera na osnovu parametra iz JSON-a.
    match (proces):
        case "Grayscale":
            proces = Vrsta_Filtera.Grayscale
        case "Gaussian Blur":
            proces = Vrsta_Filtera.Gaussian_Blur
        case "Brightness Adjustment":
            proces = Vrsta_Filtera.Brightness_Adjustment

    # Dohvatanje ID-a originalne slike.
    id_originala = params.get("slika_id")
    original_slika = None


    registar_slika.lock.acquire()
    # Pretraga originalne slike po ID-u u registru slika.
    for slika in registar_slika.niz_slika:
        if int(id_originala) == int(slika.slika_id):
            original_slika = slika
    registar_slika.lock.release()

    if original_slika.delete_flag == 1: # slika oznacena za brisanje, ne moze da joj se pristupi
        red_za_poruke.put("Ova slika je rezervisana za brisanje")
        return

    # Kreiranje nove putanje za kopiju slike i kopiranje njenih filtera.
    putanja_kopije = params.get("putanja")
    filteri_kopije = []
    for filter in original_slika.tip_filtera:
        filteri_kopije.append(filter)
    filteri_kopije.append(proces)  # Dodavanje trenutnog filtera u listu.

    # Kopiranje prethodnih roditelja slike
    preci_kopije = []
    for preci in original_slika.preci:
        preci_kopije.append(preci)
    preci_kopije.append(original_slika)  # Dodavanje trenutne slike u niz roditelja.

    # Kreiranje nove slike koja predstavlja kopiju sa dodatim filterima.
    kopija_slike = Slika(putanja_kopije, putanja_kopije.split("\\")[-1], 0, [], 0, filteri_kopije, preci_kopije)

    # Kreiranje novog zadatka za obradu slike.
    proces_zadatak = Zadatak(original_slika.slika_id, kopija_slike.slika_id, proces)
    kopija_slike.zadatak_id = proces_zadatak.zadatak_id

    # Dodavanje kopije slike u registar slika.
    registar_slika.lock.acquire()
    registar_slika.niz_slika.append(kopija_slike)
    registar_slika.lock.release()

    # Dodavanje novog zadatka u registar zadataka.
    registar_zadatak.lock.acquire()
    registar_zadatak.niz_zadatak.append(proces_zadatak)
    registar_zadatak.lock.release()

    # Provera da li su svi postojeći zadaci završeni pre nego što se započne novi.
    for zadatak in original_slika.zadaci_lista: # pauziramo sve dok se ne izvrse zadaci koji su vec u cekanju
        if zadatak.status != Status.Zavrseno:
            with zadatak.condition:
                zadatak.condition.wait()

    # Dodavanje zadatka u listu zadataka slike i postavljanje statusa na "u obradi".
    original_slika.zadaci_lista.append(proces_zadatak) #ubaci se kada si zavrsio sa cekanjem
    proces_zadatak.status = Status.U_obradi

    # Pokretanje obrade slike asinhrono pomoću `pool` objekta.
    pool.apply_async(procesuiranje, args = (proces_zadatak.zadatak_id, original_slika.putanja, putanja_kopije, proces), callback = obrada_zadatka).get()



# Funkcija za obradu slika(onaj deo sa procesima):
#Učitava sliku, primenjuje filter i čuva rezultat na novu putanju.
def procesuiranje(zadatak_id, original_slika, putanja_kopije, proces):
    print(proces)  # Štampa trenutno primenjeni filter.
    kopija = load_image(original_slika) # Učitavanje originalne slike.
    slika_sa_filterom = None

    # Primena odgovarajućeg filtera.
    if proces == "Grayscale":
        slika_sa_filterom = grayscale(kopija)
    elif proces == "Gaussian Blur":
        slika_sa_filterom = gaussian_blur(kopija, sigma=3)
    elif proces == "Brightness Adjustment":
        slika_sa_filterom = adjust_brightness(kopija, factor=1.0)

    # Konverzija slike u odgovarajući format za čuvanje.
    slika_sa_filterom = Image.fromarray(slika_sa_filterom)

    print(putanja_kopije) # Štampa putanju gde će kopija biti sačuvana.

    slika_sa_filterom.save(putanja_kopije) # Čuvanje obrađene slike.

    return zadatak_id # Vraćanje ID-a zadatka.


# Funkcija za ažuriranje statusa zadatka nakon obrade.
def obrada_zadatka(zadatak_id):
    global red_za_zadatke
    red_za_zadatke.put(zadatak_id)


# Funkcija koja obrađuje red za zadatke i ažurira njihove statuse.
def obrada_reda_za_zadatke(registar_zadatak, red_za_zadatke, shut_down):

     while (not shut_down.is_set()):
        if red_za_zadatke.empty() == False:
            odradjen_id = red_za_zadatke.get()
            registar_zadatak.lock.acquire()
            # Ažuriranje statusa zadatka na "završeno".
            for zadatak in registar_zadatak.niz_zadatak:
                if int(odradjen_id) == int(zadatak.zadatak_id):
                    zadatak.status = Status.Zavrseno
                    with zadatak.condition:
                        zadatak.condition.notify_all() # obavestava druge niti
            registar_zadatak.lock.release()


#Nit za obradu komandi
#Na osnovu unete komande, pokreće odgovarajuću nit koja izvršava željenu akciju.
def process_command(command, registar_slika, registar_zadatak, red_za_poruke, pool, shut_down):
    # Razdvaja korisničku komandu na delove koristeći razmak kao separator.
    # Prvi deo komande je ključna reč (npr. "dodaj", "obrisi"), a ostali su argumenti.
    izvrsavanje = command.split(" ")
    if izvrsavanje[0] == "dodaj":
        # Kreira novu nit za dodavanje slike i pokreće je.
        # Prosleđuje drugi deo komande (putanju slike) i registar slika kao argumente.
        dodavanje_thread = threading.Thread(target = dodaj_sliku,args=(izvrsavanje[1], registar_slika))
        dodavanje_thread.start()

    elif izvrsavanje[0] == "obrisi":
        brisanje_thread = threading.Thread(target=obrisi_sliku,args=(izvrsavanje[1], registar_slika))
        brisanje_thread.start()

    elif izvrsavanje[0] == "izlistaj":
        izlistaj_thread = threading.Thread(target=izlistaj_slike,args=(registar_slika, red_za_poruke))
        izlistaj_thread.start()

    elif izvrsavanje[0] == "opisi":
        opisi_thread = threading.Thread(target=opisi_sliku,args=(izvrsavanje[1], registar_slika, red_za_poruke))
        opisi_thread.start()

    elif izvrsavanje[0] == "izadji":
        izadji_thread = threading.Thread(target=izadji_komanda, args=(shut_down, ))
        izadji_thread.start()
    elif izvrsavanje[0] == "obradi":
        obrada_thread = threading.Thread(target=process_thread, args=(izvrsavanje[1], registar_slika, registar_zadatak,red_za_poruke, pool))
        obrada_thread.start()
    else:
        print(f"Nepoznata komanda: {command}")



#Glavna nit: čeka korisničke komande i pokreće odgovarajuće niti.
def glavni_thread():
    registar_slika = Registar_slika([]) # kreira registar slika
    registar_zadatak = Registar_zadatak([]) #kreira registar zadataka
    print(registar_slika.niz_slika)
    red_za_poruke = Queue() # Kreira red za poruke koji će sadržati tekstualne odgovore za korisnika.
    pool = mp.Pool(mp.cpu_count() - 2)  # Pool za paralelnu obradu, uzeo 2 procesora manje
    global red_za_zadatke    # Globalni red za završene zadatke (koristi se za sinhronizaciju).
    red_za_zadatke = Queue() # smaštamo identifikatore zadataka koji su završeni
    shut_down = Event()  # Signal za gašenje programa - koristi se za prekid petlje u glavnoj niti.

    # Kreira i pokreće nit koja prati red za završene zadatke.
    # Kada zadatak završi, ažurira njegov status.
    obrada_zadatka = threading.Thread(target = obrada_reda_za_zadatke, args=(registar_zadatak, red_za_zadatke, shut_down))
    obrada_zadatka.start()

# ceka na komande sa ulaza
    # Glavna petlja programa - čeka na korisničke komande dok shut_down nije aktiviran.
    while (not shut_down.is_set()): # shut_down je signal za gasenje
        komanda = input("Komanda: ")
        #kreira i pokrece nit za obradu komandi
            # Prosleđuje komandu funkciji `process_command` na obradu.
        process_command(komanda, registar_slika, registar_zadatak, red_za_poruke, pool, shut_down)
        if red_za_poruke.empty() == False: # tekst koji ce da ispise na komandnu liniju
            while red_za_poruke.empty() == False:
                print(red_za_poruke.get(timeout=0.5))
    # Kada se shut_down aktivira, zatvara redove za poruke i zadatke, kao i pool procesa.
    red_za_poruke.close()
    red_za_zadatke.close()
    pool.close()

if __name__ == "__main__":
    glavni_thread = threading.Thread(target=glavni_thread)
    glavni_thread.start()
    glavni_thread.join()

