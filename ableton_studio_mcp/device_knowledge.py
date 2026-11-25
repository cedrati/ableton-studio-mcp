"""What every device does: Live's native instruments, audio and MIDI
effects, the Max for Live devices bundled with Live 12, and common
third-party plug-in families, for inventories and device choice.

Native entries are summarised from the Ableton Live 12 manual (Live
Instrument / Audio Effect / MIDI Effect Reference, MIDI Tools, Max for Live
Devices). Each entry: kind, category, what it is for, key parameters (Live's
names), electronic/techno uses, and whether it has a sidechain input.
"""

import re
from typing import Dict, List, Optional


def _d(kind, category, what, params, uses, sidechain=False, tip=""):
    return {"kind": kind, "category": category, "what": what, "key_parameters": params,
            "electronic_uses": uses, "sidechain": sidechain, "tip": tip}


I, A, M, X = "instrument", "audio_effect", "midi_effect", "max_for_live"

NATIVE: Dict[str, Dict] = {
    # ---------------------------------------------------------- instruments
    "Analog": _d(I, "synthèse soustractive (modélisation analogique)",
                 "Synthé virtuel analogique : 2 oscillateurs, bruit, 2 filtres, 2 enveloppes et LFO.",
                 "Shape, Freq, Reso, Drive, F1/F2, Sub/Sync, Attack/Decay/Sustain/Release",
                 "Basses, leads et nappes analogiques chaudes ; Sync et Sub pour des timbres agressifs.",
                 tip="Mapper la molette de modulation sur le ratio de Sync pour un son analogique très rugueux."),
    "Collision": _d(I, "modélisation physique (maillets, résonateurs)",
                    "Percussions à maillets simulées : excitateurs Mallet/Noise et deux résonateurs.",
                    "Stiffness, Noise, Resonance Type, Decay, Material, Radius, Brightness, Inharm",
                    "Percussions métalliques et mélodiques, cloches, textures résonantes.",
                    tip="Excitateur Noise + enveloppes longues = textures quasi granulaires ; garder les niveaux bas."),
    "Drift": _d(I, "synthèse soustractive (MPE, légère)",
                "Synthé soustractif simple et économe, chaque voix légèrement instable (Drift).",
                "Osc 1, Shape, Freq, Res, Type I/II, Drift, Voice Mode, Glide",
                "Basses acid (Mono + Glide), leads, pads vivants.",
                tip="Un LFO en mode Ratio sur la hauteur des oscillateurs produit des sons FM."),
    "Drum Sampler": _d(I, "échantillonneur one-shot (Drum Rack)",
                       "Lecture de samples one-shot pour Drum Racks, enveloppe AHD, filtre, effets de lecture.",
                       "Sample Start, Sample Length, Attack, Hold, Decay, Filter Frequency, Playback Effect",
                       "Kicks, snares, hats ; effets Punch, Sub Osc, 8-Bit pour renforcer ou salir.",
                       tip="« Envelope Follows Pitch » garde le même passage du sample quand on transpose."),
    "Electric": _d(I, "modélisation physique (piano électrique)",
                   "Piano électrique modélisé (lames, marteaux, micro) sans échantillons.",
                   "Stiffness, Force, Tine Decay, Tone, Symmetry, Distance",
                   "Accords deep house, Rhodes, nappes chaudes."),
    "External Instrument": _d(I, "routage matériel",
                              "Envoie le MIDI vers un synthé matériel/plug-in multitimbral et récupère son audio.",
                              "MIDI To, Audio From, Gain, Hardware Latency",
                              "Intégrer synthés et boîtes à rythmes matériels (Elektron, etc.).",
                              tip="Latence en samples pour une liaison numérique, en ms pour une liaison analogique."),
    "Impulse": _d(I, "échantillonneur de batterie (8 slots)",
                  "Boîte à rythmes à 8 samples avec stretch, filtre, saturation, enveloppe.",
                  "Start, Transp, Stretch, Filter Frequency, Resonance, Drive, Decay",
                  "Kits techno rapides ; Drive pour des kicks saturés.",
                  tip="Bouton Link entre slots 7 et 8 : le charley fermé coupe l'ouvert."),
    "Meld": _d(I, "synthé à deux moteurs « macro » + matrice de modulation",
               "Deux moteurs d'oscillateurs dont les macros changent selon le type, filtres variés.",
               "Oscillator Type, macros, Filter Type, Filter Frequency, Q, Drive, Modulation Matrix",
               "Textures, drones, sons évolutifs, percussions à base de bruit.",
               tip="Désactiver Osc Key Tracking fait jouer un C3 constant (drones, percussions)."),
    "Operator": _d(I, "synthèse FM (+ soustractive et additive)",
                   "4 oscillateurs FM, 11 algorithmes, filtre, LFO, enveloppes par oscillateur.",
                   "Algorithm, Coarse, Fine, Level, Feedback, Wave, Filter Freq, Filter Res, Voices",
                   "Basses FM, sons métalliques, percussions, cloches ; base de nombreux presets.",
                   tip="Le LFO en mode bruit est la clé de bons hi-hats et snares synthétiques."),
    "Sampler": _d(I, "échantillonneur multisample",
                  "Multisampling avec zones clavier/vélocité/sélection, modulation poussée.",
                  "Key Zone, Velocity Zone, Sample Start, Loop, Filter, enveloppes",
                  "Instruments multi-échantillonnés, layers, round robin.",
                  tip="Round Robin « Other » : aléatoire sans jamais répéter le même sample deux fois."),
    "Simpler": _d(I, "échantillonneur (Classic, One-Shot, Slicing)",
                  "Joue un sample avec enveloppes, filtre, LFO et warp ; découpe en slices.",
                  "Mode, Warp, Start, Length, Loop, Filter Freq, Attack/Decay/Sustain/Release",
                  "Boucles et breaks calés au tempo, slicing de breaks, one-shots, voix.",
                  tip="Snap cale les marqueurs de boucle sur les passages par zéro (moins de clics)."),
    "Tension": _d(I, "modélisation physique (cordes)",
                  "Émule les instruments à cordes : excitateur, corde, amortisseur, micro, caisse.",
                  "Exciter Type, Damper, Pickup, Termination, Body",
                  "Plucks, cordes, textures harmoniques."),
    "Wavetable": _d(I, "synthèse wavetable",
                    "2 oscillateurs wavetable, sub, 2 filtres, unisson et matrice de modulation.",
                    "Wavetable position, Unison, Filter type/freq, Mod Matrix, enveloppes",
                    "Basses, leads et pads évolutifs, supersaws (unisson), balayages de table.",
                    tip="Désactiver Hi-Quality économise jusqu'à ~25 % de CPU."),
    "Drum Rack": _d(I, "rack (batterie)",
                    "Rack de 128 pads, chacun avec sa chaîne (sampler + effets), sends et retours internes.",
                    "pads, chaînes, Choke, macros",
                    "Kits de batterie, 909/808, layering de kicks.",
                    tip="Mettre charleys fermé et ouvert dans le même groupe de choke."),
    "Instrument Rack": _d(I, "rack", "Combine plusieurs instruments/effets en chaînes parallèles avec macros.",
                          "chaînes, zones clé/vélocité/sélection, macros, variations",
                          "Layers de synthés, splits, macros de performance."),
    "Granulator III": _d(X, "synthèse granulaire (Max for Live)",
                         "Synthétiseur granulaire de Robert Henke, à partir d'un sample.",
                         "Position, Grain Size, Spray, Shape, Scan", "Textures, drones, pads ambient."),
    "DS Kick": _d(X, "batterie synthétique (Max for Live)", "Grosse caisse synthétique (sinus modulé).",
                  "Pitch, Decay, Attack, Drive, Env", "Kicks techno sur mesure, rumble."),
    "DS Snare": _d(X, "batterie synthétique (Max for Live)", "Caisses claires synthétiques.", "Tone, Decay, Noise",
                   "Snares électroniques, gated."),
    "DS Clap": _d(X, "batterie synthétique (Max for Live)", "Claps électroniques ou organiques, largeur réglable.",
                  "Tone, Decay, Spread", "Claps 909-like, couches de claps."),
    "DS HH": _d(X, "batterie synthétique (Max for Live)", "Hi-hats à partir de bruit et de sinus.", "Tone, Decay",
                "Charleys fermés à ouverts."),
    "DS Cymbal": _d(X, "batterie synthétique (Max for Live)", "Cymbales, du ride léger au crash.", "Tone, Decay",
                    "Rides, crashs."),
    "DS Tom": _d(X, "batterie synthétique (Max for Live)", "Toms synthétiques.", "Pitch, Decay", "Toms, percussions."),
    "DS FM": _d(X, "batterie synthétique (Max for Live)", "Percussions FM, du statique au métallique.",
                "Tone, Feedback, Decay", "Percussions métalliques techno."),
    "DS Clang": _d(X, "batterie synthétique (Max for Live)", "Cowbell, clave, percussions bruitées.", "Tone, Decay",
                   "Cowbells, claves électroniques."),
    # -------------------------------------------------------- audio effects
    "Amp": _d(A, "simulation d'ampli", "Émule 7 amplis guitare classiques.", "Gain, Volume, Bass, Middle, Treble, Presence",
              "Grain analogique sur synthés et batteries (avec Cabinet)."),
    "Auto Filter": _d(A, "filtre", "10 types de filtres analogiques modulés par LFO ou enveloppe.",
                      "Filter Type, Freq, Res, Drive, Filter Circuit, LFO Amount", "Balayages, wobbles, lignes acid, filtrage déclenché par le kick.",
                      sidechain=True),
    "Auto Pan-Tremolo": _d(A, "modulation", "Panoramique, trémolo ou gate automatiques par LFO.",
                           "Waveform, Amount, Shape, Invert, Rate", "Pan rythmique de hats, pompage, trance gate."),
    "Auto Shift": _d(A, "pitch / voix", "Correction de hauteur temps réel, vibrato, pitch et formants.",
                     "Correction Strength, Pitch Shift, Formant Shift, Vibrato", "Voix corrigées, harmonisation, effets vocaux."),
    "Beat Repeat": _d(A, "rythmique / répétitions", "Répétitions du signal calées au tempo, contrôlées ou aléatoires.",
                      "Interval, Chance, Gate, Grid, Variation, Pitch", "Stutters, glitchs, fills de batterie."),
    "Cabinet": _d(A, "simulation de baffle", "Émule 5 baffles guitare (après Amp).", "Speaker, Microphone, Dry/Wet",
                  "Coloration de synthés et batteries."),
    "Channel EQ": _d(A, "EQ", "EQ trois bandes façon console, avec coupe-bas 80 Hz.", "HP 80 Hz, Low, Mid, High",
                     "Mise en place rapide de pistes."),
    "Chorus-Ensemble": _d(A, "modulation", "Chorus, ensemble et vibrato à lignes de délai modulées.",
                          "Mode, Rate, Amount, Feedback, Width, Dry/Wet", "Élargir pads et synthés."),
    "Color Limiter": _d(A, "dynamique / saturation", "Limiteur coloré, inspiré du matériel, qui sature au lieu d'écrêter.",
                        "Ceiling, Saturation, Loudness", "Écraser une batterie, bus agressif."),
    "Compressor": _d(A, "dynamique", "Compresseur (peak/RMS/expand) avec sidechain externe et EQ de sidechain.",
                     "Threshold, Ratio, Attack, Release, Makeup, Dry/Wet",
                     "Ducking de la basse ou des pads sur le kick (sidechain), pompage, contrôle des crêtes.",
                     sidechain=True, tip="Le sidechain se route par l'API (input routing) : voir set_device_sidechain."),
    "Corpus": _d(A, "résonateur (modélisation physique)", "Simule 7 objets résonants (plaque, tube, membrane...).",
                 "Resonance Type, Decay, Material, Radius, Tune", "Percussions métalliques, résonances sur batteries."),
    "Delay": _d(A, "delay", "Délai stéréo, lignes indépendantes, filtre passe-bande, LFO, Freeze.",
                "Feedback, Freeze, Filter Freq, Width, Ping Pong, Dry/Wet", "Échos rythmiques, boucles gelées."),
    "Drum Buss": _d(A, "traitement de batterie", "Ajoute corps, transitoires et grave à un bus de batterie.",
                    "Drive, Crunch, Transients, Boom, Boom Freq, Dry/Wet", "Kick plus percutant, bus de drums saturé, Boom accordé."),
    "Dynamic Tube": _d(A, "saturation", "Saturation à lampes dont la distorsion suit le niveau.", "Tube, Drive, Tone, Bias, Envelope",
                       "Chaleur sur basses et batteries."),
    "Echo": _d(A, "delay", "Délai modulé à deux lignes, caractère bande, réverbe, ducking.",
               "Feedback, Sync, Reverb, Wobble, Repitch, Dry/Wet", "Dub delays, échos sales, ducking automatique."),
    "EQ Eight": _d(A, "EQ", "EQ paramétrique 8 bandes, modes Stéréo/L-R/M-S, analyseur.",
                   "Filter Type, Frequency, Gain, Q, Mode, Adaptive Q", "Nettoyage, sculpter kick/basse, coupes M/S."),
    "EQ Three": _d(A, "EQ DJ", "EQ trois bandes avec coupure totale (kill).", "Low, Mid, High, FreqLo, FreqHi",
                   "Transitions DJ, coupes de basses en live."),
    "Erosion": _d(A, "dégradation numérique", "Délai court modulé et bruit filtré pour salir le son.", "Freq, Amount, Noise Blend",
                  "Hats dégradés, textures lo-fi."),
    "External Audio Effect": _d(A, "routage matériel", "Envoie l'audio vers un effet matériel et le récupère.",
                                "Audio To, Audio From, Dry/Wet, Hardware Latency", "Passer un bus dans une machine analogique."),
    "Filter Delay": _d(A, "delay", "Trois délais filtrés (gauche, droite, stéréo).", "Delay Time, Feedback, filtres, Pan",
                       "Échos filtrés, dub techno."),
    "Gate": _d(A, "dynamique", "Ne laisse passer que ce qui dépasse un seuil ; sidechain.", "Threshold, Return, Attack, Hold, Release, Floor",
               "Découper un pad au rythme du kick, nettoyer.", sidechain=True),
    "Glue Compressor": _d(A, "dynamique de bus", "Compresseur de bus façon console analogique (SSL).",
                          "Threshold, Ratio, Attack, Release, Range, Makeup", "Coller un bus de drums ou le master, pompage léger.",
                          sidechain=True),
    "Grain Delay": _d(A, "delay granulaire", "Découpe en grains retardés et transposés.", "Spray, Frequency, Pitch, Feedback",
                      "Textures granulaires, effets."),
    "Hybrid Reverb": _d(A, "réverbe", "Réverbe convolution + algorithmique, IR importables.", "Blend, Predelay, Decay, Size, Freeze",
                        "Espaces, nappes, réverbes de retour, cathédrales."),
    "Limiter": _d(A, "dynamique / mastering", "Limiteur de mastering (plafond, true peak).", "Gain, Ceiling, Release, Lookahead",
                  "Dernier device du master, contrôle des crêtes."),
    "Looper": _d(A, "boucleur", "Enregistre et superpose des boucles audio en temps réel.", "Feedback, Reverse, Quantization, Speed",
                 "Performance live, boucles de synthé."),
    "Multiband Dynamics": _d(A, "dynamique multibande", "Compression/expansion sur 3 bandes ; OTT en preset.",
                             "Amount, Time, Below/Above, Input, Output", "Compression de master, OTT sur synthés, dé-essage.",
                             sidechain=True),
    "Overdrive": _d(A, "distorsion", "Distorsion de pédale avec filtre passe-bande.", "Drive, Tone, Dynamics", "Saturer drums, basses, leads."),
    "Pedal": _d(A, "distorsion", "Overdrive, Distortion, Fuzz avec EQ et Sub.", "Gain, Bass, Mid, Treble, Sub",
                "Kick techno saturé (Sub + Bass), fuzz sur bus."),
    "Phaser-Flanger": _d(A, "modulation", "Phaser, flanger, doubler, deux LFO et suiveur d'enveloppe.",
                         "Feedback, Amount, Rate, Dry/Wet", "Balayages de phaser, flanger sur hats."),
    "Redux": _d(A, "bitcrusher", "Réduction de fréquence d'échantillonnage et de bits.", "Rate, Jitter, Bits, Shape",
                "Lo-fi, crunch de batterie."),
    "Resonators": _d(A, "résonateurs", "Cinq résonateurs accordables en parallèle.", "Note, Decay, Color, Width",
                     "Accords résonants sur percussions."),
    "Reverb": _d(A, "réverbe", "Réverbe algorithmique (filtres, lignes de délai modulées), Freeze.",
                 "Predelay, Size, Decay, Freeze, Stereo, Dry/Wet", "Espaces, réverbe de retour, son infini (Freeze)."),
    "Roar": _d(A, "saturation multi-étages", "Jusqu'à 3 étages de saturation, routage série/parallèle/multibande, feedback.",
               "Drive, Routing, Shaper Type, Feedback, Blend", "Distorsion de kick/basse, feedback, saturation pilotée.",
               sidechain=True),
    "Saturator": _d(A, "saturation", "Waveshaping, de la chaleur à la distorsion lourde.", "Curve Type, Drive, Color, Output",
                    "Saturer drums, 808, basses ; Bass Shaper."),
    "Shifter": _d(A, "pitch / fréquence", "Décalage de hauteur, de fréquence, ring modulation.", "Pitch, Freq, Ring, Mode",
                  "Sons métalliques, ring mod."),
    "Spectral Resonator": _d(A, "spectral", "Résonances accordées sur le spectre, contrôle MIDI.", "Freq, Decay, Shift, Stretch",
                             "Rendre une batterie tonale, effet vocodeur."),
    "Spectral Time": _d(A, "spectral", "Gel et délai spectraux.", "Freezer, Delay, Time, Feedback, Spray",
                        "Drones, délais spectraux."),
    "Spectrum": _d(A, "analyse", "Analyseur de spectre (affichage seulement, non lisible par l'API).",
                   "Block, Range, Avg, Scale", "Contrôle visuel du spectre."),
    "Tuner": _d(A, "accordage", "Accordeur (affichage).", "Reference, Mode", "Accorder un kick ou un sample."),
    "Utility": _d(A, "utilitaire", "Gain, phase, largeur, mono, Bass Mono, mute.", "Gain, Width, Mono, Bass Mono, Bass Mono Frequency",
                  "Graves en mono (Bass Mono), réglage de niveau, stéréo."),
    "Vinyl Distortion": _d(A, "lo-fi", "Distorsions de lecture vinyle et crépitements.", "Tracing Model, Pinch, Crackle",
                           "Texture vintage, crackle."),
    "Vocoder": _d(A, "spectral", "Applique l'enveloppe d'un modulateur sur une porteuse.", "Carrier, Bands, Formant, Dry/Wet",
                  "Voix robot, textures.", sidechain=True),
    "Audio Effect Rack": _d(A, "rack", "Chaînes d'effets parallèles avec macros.", "chaînes, macros, variations",
                            "Multibande maison, effets parallèles, macros de performance."),
    "LFO": _d(X, "modulateur (Max for Live)", "Module un ou plusieurs paramètres mappés par un LFO.", "Rate, Depth, Shape, Map",
              "Mouvements lents de filtre, wobbles (le mapping se fait dans l'interface)."),
    "Envelope Follower": _d(X, "modulateur (Max for Live)", "Transforme l'amplitude d'un signal en modulation.", "Gain, Rise, Fall, Map",
                            "Faire réagir un filtre à la batterie."),
    "Shaper": _d(X, "modulateur (Max for Live)", "Modulation par enveloppe à points dessinée.", "Rate, Depth, Map",
                 "Courbes rythmiques sur filtre/volume."),
    "Align Delay": _d(X, "utilitaire (Max for Live)", "Retarde un signal (ms, samples, distance).", "Delay",
                      "Aligner deux sources, compenser une latence."),
    # --------------------------------------------------------- MIDI effects
    "Arpeggiator": _d(M, "MIDI", "Arpège les accords joués.", "Style, Rate, Distance, Steps, Gate, Retrigger",
                      "Arpèges trance/synthwave, séquences."),
    "CC Control": _d(M, "MIDI", "Envoie des CC vers du matériel.", "Mod Wheel, Pitch Bend, Custom", "Automatiser un synthé matériel."),
    "Chord": _d(M, "MIDI", "Ajoute jusqu'à 6 notes à chaque note jouée.", "Shift 1-6, Velocity, Chance, Strum",
                "Stabs d'accords en une note (dub techno), nappes."),
    "Note Length": _d(M, "MIDI", "Change la durée des notes.", "Gate, Length, Trigger", "Staccato/legato."),
    "Pitch": _d(M, "MIDI", "Transpose en demi-tons ou en degrés de gamme.", "Pitch, Step Width, Range, Mode",
                "Transposer une ligne, couches d'octave."),
    "Random": _d(M, "MIDI", "Aléa sur la hauteur des notes.", "Chance, Choices, Interval, Mode", "Variations de séquences."),
    "Scale": _d(M, "MIDI", "Ramène les notes dans une gamme.", "Base, Scale Name, Transpose, Fold", "Jouer juste dans une gamme."),
    "Velocity": _d(M, "MIDI", "Remappe les vélocités.", "Out Hi, Out Low, Drive, Compand, Random", "Lisser ou humaniser."),
    "MIDI Effect Rack": _d(M, "rack", "Chaînes d'effets MIDI parallèles.", "chaînes, macros", "Layers d'arpèges, splits."),
    "Expression Control": _d(X, "modulateur MIDI (Max for Live)", "Mappe vélocité, molette, pression, slide sur des paramètres.",
                             "Source, Min/Max, Curve", "Modulation expressive."),
    "MPE Control": _d(X, "MIDI (Max for Live)", "Façonne les données MPE.", "Press, Slide, NotePB", "Contrôleurs MPE."),
    "Note Echo": _d(X, "MIDI (Max for Live)", "Répète les notes avec décroissance et transposition.", "Time, Pitch, Feedback",
                    "Échos MIDI rythmiques."),
    "Envelope MIDI": _d(X, "modulateur MIDI (Max for Live)", "Enveloppe ADSR par note vers des paramètres.",
                        "Attack, Decay, Sustain, Release, Map", "Enveloppe de filtre par note."),
    "Shaper MIDI": _d(X, "modulateur MIDI (Max for Live)", "Enveloppe dessinée déclenchée par note.", "Breakpoints, Map",
                      "Modulations rythmiques par note."),
    "MIDI Monitor": _d(X, "MIDI (Max for Live)", "Affiche le MIDI entrant.", "-", "Débogage de contrôleurs."),
    # ------------------------------------------- legacy (Audio Effects/Legacy)
    # Names as Live 12 shows them; parameters read in Live 12 Suite.
    "Auto Filter Legacy": _d(A, "filtre (ancienne version)",
                             "Auto Filter d'avant Live 12.2, gardé pour ouvrir les anciens projets à l'identique.",
                             "Filter Type, Frequency, Resonance, Drive, Env. Modulation, LFO Amount, LFO Frequency, S/C On",
                             "Balayages de filtre, ducking par sidechain dans d'anciens sets.", sidechain=True,
                             tip="Pour un nouveau son, préférer Auto Filter."),
    "Auto Pan Legacy": _d(A, "modulation (ancienne version)", "Panoramique et trémolo par LFO, remplacé par Auto Pan-Tremolo.",
                          "Amount, Frequency, Sync Rate, Phase, Waveform, Shape, Invert",
                          "Trémolo, panoramique rythmique, faux sidechain (Shape + Invert).",
                          tip="Pour un nouveau son, préférer Auto Pan-Tremolo."),
    "Chorus": _d(A, "modulation (ancienne version)", "Chorus à deux délais modulés, remplacé par Chorus-Ensemble.",
                 "Delay 1 Time, Delay 2 Time, LFO Amount, LFO Rate, Feedback, Dry/Wet", "Élargir nappes et leads.",
                 tip="Pour un nouveau son, préférer Chorus-Ensemble."),
    "Erosion Legacy": _d(A, "lo-fi (ancienne version)", "Erosion d'avant la mise à jour : dégradation par bruit ou sinus modulé.",
                         "Mode, Frequency, Amount, Width", "Grain numérique, aliasing sur hats et voix.",
                         tip="Pour un nouveau son, préférer Erosion."),
    "Flanger": _d(A, "modulation (ancienne version)", "Flanger à délai court modulé, remplacé par Phaser-Flanger.",
                  "Delay Time, Feedback, LFO Amount, Frequency, Env. Modulation, Dry/Wet",
                  "Jet sur hats et caisses claires, montées.",
                  tip="Pour un nouveau son, préférer Phaser-Flanger."),
    "Frequency Shifter": _d(A, "pitch / fréquence (ancienne version)", "Décalage de fréquence et ring modulation, remplacé par Shifter.",
                            "Mode, Coarse, Fine, Ring Mod Frequency, Drive, LFO Amount, Dry/Wet",
                            "Sons métalliques, ring mod, désaccords inharmoniques.",
                            tip="Pour un nouveau son, préférer Shifter."),
    "Phaser": _d(A, "modulation (ancienne version)", "Phaser à filtres passe-tout, remplacé par Phaser-Flanger.",
                 "Poles, Color, Frequency, Feedback, LFO Amount, LFO Frequency, Dry/Wet",
                 "Mouvement lent sur nappes et accords.",
                 tip="Pour un nouveau son, préférer Phaser-Flanger."),
    "Redux Legacy": _d(A, "lo-fi (ancienne version)", "Redux d'avant Live 11 : réduction de fréquence d'échantillonnage et de résolution.",
                       "Bit On, Bit Depth, Sample Mode, Sample Hard, Sample Soft", "Textures 8 bits, crunch sur batterie.",
                       tip="Pour un nouveau son, préférer Redux."),
}

# Max for Live devices from Ableton's official Packs (installed separately
# from the Core Library). Descriptions are functional, no artist names;
# parameter names were read in Live 12 Suite.
PACK_DEVICES: Dict[str, Dict] = {
    # Creative Extensions
    "Bass": _d(X, "instrument (Max for Live)", "Synthé de basse monophonique virtuel analogique (pulse, sync, ring mod).",
               "Octave, Pulse Width, Sync, Ring Mod, Cutoff, Res, Filter Type, Filter Env, Drive, Glide",
               "Basses rondes ou acides, sub."),
    "Poli": _d(X, "instrument (Max for Live)", "Synthé polyphonique virtuel analogique au caractère vintage, chorus intégré.",
               "Saw, Pulse, Pulse Width, Sub, Noise, Xmod, Ring, LPF, HPF, Res, AD Loop, Chorus, Unison Spread, Glide",
               "Nappes et accords 80s, stabs."),
    "Gated Delay": _d(X, "délai (Max for Live)", "Délai dont l'entrée est ouverte par un séquenceur de gate.",
                      "Steps, Rate, Delay, Feedback, Duck, Random, Dry / Wet",
                      "Échos rythmiques qui ne répètent que certains pas."),
    "Pitch Hack": _d(X, "pitch / délai (Max for Live)", "Délai avec transposition, inversion et réinjection.",
                     "Coarse, Cents, Rate, Recycle, Reverse, Int Var, Dry / Wet", "Échos transposés, effets glitch."),
    "Re-Enveloper": _d(X, "dynamique (Max for Live)", "Remodèle l'enveloppe de trois bandes de fréquence (compression/expansion).",
                       "Split 1, Split 2, Attack, Release, C/E Fact, Vol (par bande), DryWet",
                       "Durcir ou adoucir les transitoires, effet d'expansion."),
    "Spectral Blur": _d(X, "spectral (Max for Live)", "Floute une plage de fréquences en nappe réverbérante.",
                        "Freq 1, Freq 2, Halo, Halo / Freeze, Residual, Wet Gain, Dry / Wet",
                        "Nappes à partir de n'importe quel son, ambiances."),
    "Melodic Steps": _d(X, "séquenceur MIDI (Max for Live)",
                        "Séquenceur mélodique à couloirs de longueurs indépendantes (octave, transposition, durée, vélocité, probabilité).",
                        "Oct Length, Transp Length, Length Length, Velo Length, Chance Length, Resync",
                        "Lignes évolutives, polymétrie entre couloirs (les pas se règlent dans l'interface)."),
    # Convolution Reverb
    "Convolution Reverb": _d(X, "réverbe (Max for Live)", "Réverbe par réponses impulsionnelles d'espaces réels et d'appareils.",
                             "Predelay, Width, Gain, EQ On, Lo/Mid/Hi Freq et Gain, Dry/Wet",
                             "Espaces réalistes, chambres, ressorts, plaques (l'IR se choisit dans l'interface)."),
    "Convolution Reverb Pro": _d(X, "réverbe (Max for Live)", "Convolution Reverb avec modulation, positionnement stéréo et EQ.",
                                 "Predelay, Width, Mod On, Mod Rate, Amount, Pos On, Pos Pan, Pos Depth, Cascade, EQ On, Dry/Wet",
                                 "Réverbe sculptée précisément."),
    "IR Measurement Device": _d(X, "utilitaire (Max for Live)", "Capture la réponse impulsionnelle d'une pièce ou d'un appareil.",
                                "Sweep, Sweep Time, IR Time, Input, Trim, Save", "Créer ses propres IR pour Convolution Reverb."),
    # Max for Live Essentials
    "LFO MIDI": _d(X, "modulateur MIDI (Max for Live)", "LFO placé sur une piste MIDI, vers des paramètres ou un CC.",
                   "Rate, Depth, Shape, Offset, Jitter, Smooth, Keytrack, Velocity, LFOCC",
                   "Mouvements suivant le clavier ou la vélocité."),
    "Map8": _d(X, "modulateur (Max for Live)", "Huit macros, chacune mappée sur un paramètre avec sa plage.",
               "Macro 1-8, Map, Min 1, Max 1, Bypass 1-8", "Macros de performance hors rack."),
    "MultiMap": _d(X, "modulateur (Max for Live)", "Un contrôle vers huit paramètres, chacun avec sa plage.",
                   "Input, Map, Min, Max", "Gestes complexes depuis un seul potard."),
    "XY Pad": _d(X, "modulateur (Max for Live)", "Pad XY qui pilote deux paramètres.",
                 "ValueX, ValueY, X Min/Max, Y Min/Max, X/Y Invert", "Morphing de filtre et de délai en live."),
    "Device Randomizer": _d(X, "utilitaire (Max for Live)", "Tire au hasard les paramètres d'un device, ponctuellement ou en continu.",
                            "Randomize, Randomness, Depth, Freq, Trigger mode, Smoothing",
                            "Chercher des accidents heureux en sound design."),
    "Mono Sequencer": _d(X, "séquenceur MIDI (Max for Live)", "Séquenceur pas à pas monophonique avec randomisation.",
                         "Pattern, Mode, Transpose, Quantize, Swing amount, Randomize velocity/octave/duration",
                         "Lignes de basse et arpèges à la main."),
    "Instant Haus": _d(X, "générateur MIDI (Max for Live)",
                       "Générateur de patterns de batterie house (kick, snare, hats, percussions) avec randomisation.",
                       "genre, Pattern, Shift, Swing, Note, Vel Hi/Lo, kick/snare/hihats/perc enable",
                       "Esquisses rapides de groove sur un Drum Rack."),
    "PitchDrop": _d(X, "pitch (Max for Live)", "Chute de hauteur façon arrêt de bande.",
                    "Drop Activate, Drop Duration, Curve, Sync Mode", "Tape stop en fin de phrase."),
    "Buffer Shuffler 2.0": _d(X, "découpe (Max for Live)", "Découpe l'audio en pas et les réordonne, inverse ou répète.",
                              "Bars, Beats, Rows, Dice, AutoDice, Freeze, Gain, DryWet",
                              "Glitch et réarrangement de breaks."),
    # CV Tools (matériel modulaire via une interface DC-coupled)
    "CV In": _d(X, "CV (Max for Live)", "Reçoit une tension de contrôle et la mappe sur un paramètre.",
                "Mode, Range, Polarity", "Moduler Live depuis un modulaire."),
    "CV Instrument": _d(X, "CV (instrument Max for Live)", "Joue un oscillateur modulaire (hauteur + gate) depuis le MIDI.",
                        "Gate, Glide, Legato, Retrigger, PB Range, Source/Min/Max 1-3",
                        "Séquencer un modulaire depuis Live (accordage dans l'interface)."),
    "CV LFO": _d(X, "CV (Max for Live)", "LFO envoyé en tension de contrôle.",
                 "Rate, Shape, Depth, Offset, Phase, Jitter, Smooth, CV Min/Max", "Moduler un modulaire en sync."),
    "CV Envelope Follower": _d(X, "CV (Max for Live)", "Suiveur d'enveloppe audio vers CV, avec déclencheur à seuil.",
                               "Gain, Rise, Fall, Thresh, Trig Mode, CV Min/Max",
                               "Faire réagir un modulaire à la batterie."),
    "CV Shaper": _d(X, "CV (Max for Live)", "Enveloppe dessinée envoyée en CV.",
                    "Rate, Depth, GridSize, Trigger Mode, Offset, Smooth", "Modulations rythmiques."),
    "CV Triggers": _d(X, "CV (instrument Max for Live)", "Envoie des triggers ou gates depuis huit notes MIDI.",
                      "Note 1-8, Trigger Length, Polarity, Mode", "Déclencher des modules de batterie."),
    "CV Utility": _d(X, "CV (Max for Live)", "Mixe, décale, atténue jusqu'à trois signaux CV.",
                     "CV 1-3, CV Amt 1-3, Offset, Smooth, CV Min/Max", "Préparer une tension."),
    "CV Clock In": _d(X, "CV (Max for Live)", "Synchronise le tempo de Live sur une horloge externe.",
                      "Clock, Thresh, Taps, Transport", "Live esclave d'un modulaire."),
    "CV Clock Out": _d(X, "CV (Max for Live)", "Envoie l'horloge de Live en impulsions.",
                       "Clock type, PPQN, Division, Swing, Trig Length", "Modulaire esclave de Live."),
    "Rotating Rhythm Generator": _d(X, "générateur MIDI (Max for Live)",
                                    "Couloirs rythmiques euclidiens à rotation, combinables par opérations logiques.",
                                    "Steps, Fill, Rotate, Euclidian, Division, Odds, Logic, Note, Velocity",
                                    "Polyrythmies qui se décalent."),
    # Sequencers
    "Rhythmic Steps": _d(X, "séquenceur MIDI (Max for Live)", "Séquenceur de batterie pas à pas à quatre couloirs.",
                         "Clock Speed, Global Shuffle, Global Len 1-4, Len Chance 1-4, Len Roll 1-4, Len Velo 1-4, Mute 1-4",
                         "Patterns de batterie avec probabilité et rolls."),
    "SQ Sequencer": _d(X, "séquenceur MIDI (Max for Live)", "Séquenceur 16 pas inspiré des séquenceurs analogiques, avec conditions.",
                       "Division, ClockSource, FollowScales, LStep 1-16, ConStep 1-16", "Lignes de basse hypnotiques."),
    "Step Arp": _d(X, "arpégiateur (Max for Live)", "Arpégiateur programmable pas à pas (ratchets, probabilité).",
                   "Division, Note Order, Swing, LoopLength, RatchetOn, ChanceOn, TranspMax/Min, LengthValue",
                   "Arpèges plus précis que l'Arpeggiator."),
    # Inspired by Nature
    "Bouncy Notes": _d(X, "générateur MIDI (Max for Live)", "Notes jouées par des balles qui rebondissent (physique).",
                       "Gravity, Speed, Friction, Height, Drop Mode, Auto Drop, Start Pitch, Note Quant",
                       "Rythmes organiques qui accélèrent."),
    "Emit": _d(X, "instrument (Max for Live)", "Instrument à particules jouant des grains d'échantillon.",
               "Emit Rate, Particle Life, Force, Friction, Pitch, Blur, Grains, Freq, Filter Q, Sample Start",
               "Textures granuleuses, gouttes."),
    "Tree Tone": _d(X, "instrument (Max for Live)", "Résonateurs organisés en arbre fractal, excités par maillet, pluie ou vent.",
                    "Tree Shape, Inharmonicity, Decay, Scale Type, Rain, Wind, Noise, Key to Mallet",
                    "Carillons et textures naturelles."),
    "Vector Delay": _d(X, "délai (Max for Live)", "Délai multi-voix déplacées par des particules (attracteur, champ de flux).",
                       "Time Sync, Time Free, Feedback, Voices, Emit Rate, Attractor, Flowfield, Filter Cut, Freeze, Mix",
                       "Échos mouvants, spatialisation."),
    "Vector FM": _d(X, "instrument (Max for Live)", "Synthé FM dont les grains sont des particules.",
                    "CarrShape, ModRatio, Index, Grains, Emit Rate, Particle Life, Attractor, Flowfield, Filter Cut",
                    "Timbres FM vivants."),
    "Vector Grain": _d(X, "instrument (Max for Live)", "Instrument granulaire piloté par particules, sur échantillon ou enregistrement.",
                       "Grains, Size Sync, Size Free, Grain Start, Emit Rate, Attractor, Record, Freeze, Filter Cut",
                       "Nuages granulaires."),
    "Vector Map": _d(X, "modulateur (Max for Live)", "Particules dont les attributs modulent huit paramètres mappés.",
                     "1-8 Attribute, 1-8 Center, 1-8 Width, Emit Rate, Attractor",
                     "Modulations imprévisibles mais continues."),
    # Divers packs officiels
    "Microtuner": _d(X, "accordage (MIDI, Max for Live)", "Accordages microtonaux (fichiers Scala ou générés), fondu entre deux gammes.",
                     "Scale Selector, Base Freq, Transpose, Blend, Blend Amount, MPE On/Off",
                     "Gammes non tempérées, drones."),
    "PitchLoop89": _d(X, "pitch / délai (Max for Live)", "Délai transpositeur stéréo au caractère de harmoniseur numérique des années 80.",
                      "Pitch L/R, Feedback L/R, Position L/R, Hi Cut L/R, Low Cut L/R, LFO Depth L/R, Hold L/R, Routing, Dry/Wet",
                      "Échos transposés, glitch vintage."),
    "Surround Panner": _d(X, "spatialisation (Max for Live)", "Panoramique surround multicanal.",
                          "X-Axis, Y-Axis, Rotation, Focus, Center, SpeakerPos", "Diffusion sur plus de deux enceintes."),
    "Expressive Chords": _d(X, "MIDI (Max for Live)", "Joue des accords depuis une note, avec strum et articulation expressifs.",
                            "Strum, Articulate, Invert, Tilt, Variation, Transpose, Vel/Slide/ModWh > ...",
                            "Accords expressifs depuis un seul doigt."),
    "Arrangement Looper": _d(X, "performance (Max for Live)", "Boucle des sections de l'Arrangement en direct.",
                             "Loop On / Off 1-4, Length Simple 1-4, Length Odds 1-4, Division Mode, Quantize Loop Start",
                             "Prolonger une partie en live."),
    "Performer": _d(X, "performance (Max for Live)", "Jusqu'à 48 contrôles de performance mappés sur des paramètres du set.",
                    "Control 01-48", "Montées et transitions en live (le mapping se fait dans l'éditeur)."),
    "Prearranger": _d(X, "performance (Max for Live)", "Enchaîne des scènes selon un ordre et des durées programmés.",
                      "aucun paramètre exposé (tout se règle dans l'interface)", "Jouer un arrangement en Session."),
    "Variations": _d(X, "performance (Max for Live)", "Stocke et rappelle des instantanés de paramètres.",
                     "Stash, Recall, Overwrite, Navigate Up/Down, Quantize, Link to Clip/Scene",
                     "Passer d'un état de mix à un autre."),
    "Iota": _d(X, "instrument (Max for Live)", "Lecteur d'échantillons en boucle très modulable.",
               "Playback Mode, Position Offset, Pitch Offset, Filter Offset, Spread, Gain Attack, Gain Decay, Gain Sustain, Gain Release",
               "Textures à partir de fragments."),
}
NATIVE.update(PACK_DEVICES)

MIDI_TOOLS_NOTE = (
    "Les MIDI Tools de Live 12 (Transform : Arpeggiate, Chop, Connect, Glissando, LFO, Ornament, Quantize, "
    "Recombine, Span, Strum, Time Warp, Velocity Shaper ; Generate : Rhythm, Seed, Shape, Stacks, Euclidean) "
    "s'utilisent dans la vue Clip ; ils ne sont pas exposés à l'API. Leurs équivalents côté serveur : "
    "transform_clip (arpeggiate, strum, quantize, swing...), write_drum_pattern (rythmes, euclidiens), "
    "write_progression (accords)."
)

# Plug-in families: pattern -> what it is. Arturia names are emulations.
PLUGINS = [
    (r"^acid v", "Arturia Acid V, émulation de la Roland TB-303 : basse acid (accent, slide, filtre résonant)."),
    (r"^analog lab", "Arturia Analog Lab : navigateur de presets de toute la V Collection."),
    (r"^arp 2600", "Arturia ARP 2600 V : synthé modulaire semi-câblé (basses, leads, sons de laboratoire)."),
    (r"^arp odyssey", "ARP Odyssey : synthé analogique duophonique (leads, basses)."),
    (r"^augmented", "Arturia Augmented : instruments hybrides échantillons + synthèse (cordes, voix, cuivres...)."),
    (r"^b-3", "Arturia B-3 V : orgue Hammond B-3 avec cabine Leslie."),
    (r"^buchla easel", "Arturia Buchla Easel V : synthèse West Coast (complexe, percussions métalliques)."),
    (r"^clavinet", "Clavinet : clavier funk percussif."),
    (r"^cmi v", "Arturia CMI V : Fairlight CMI, échantillonneur 8 bits années 80."),
    (r"^cp-70", "Arturia CP-70 V : piano électro-acoustique Yamaha CP-70."),
    (r"^cs-80", "Arturia CS-80 V, Yamaha CS-80 (Vangelis, Blade Runner) : nappes et cuivres expressifs."),
    (r"^cz v", "Arturia CZ V : Casio CZ, synthèse à distorsion de phase."),
    (r"^dx7", "Arturia DX7 V : Yamaha DX7, synthèse FM (basses FM, cloches, e-pianos)."),
    (r"^emulator", "Arturia Emulator II V : échantillonneur E-mu années 80."),
    (r"^jun-6", "Arturia Jun-6 V : Roland Juno-6 (nappes, basses, chorus)."),
    (r"^jup-8", "Arturia Jup-8 V : Roland Jupiter-8 (nappes, leads, cuivres)."),
    (r"^mini v", "Arturia Mini V : Minimoog (basses et leads)."),
    (r"^ms-20", "Arturia MS-20 V : Korg MS-20 (filtres agressifs)."),
    (r"^ob-xa", "Arturia OB-Xa V : Oberheim OB-Xa (cuivres, nappes 80s)."),
    (r"^prophet", "Arturia Prophet V : Sequential Prophet-5 / VS."),
    (r"^sem v", "Arturia SEM V : Oberheim SEM (filtre multimode)."),
    (r"^pigments", "Arturia Pigments : synthé wavetable/granulaire/modélisé moderne."),
    (r"^synclavier", "Arturia Synclavier V : FM/additive New England Digital."),
    (r"^vocoder v", "Arturia Vocoder V : vocodeur."),
    (r"^stage-73|^wurli|^piano v", "Arturia : piano / piano électrique."),
    (r"^comp fet-76", "Arturia Comp FET-76, UREI 1176 : compresseur FET rapide (batteries, voix, punch)."),
    (r"^comp vca-65", "Arturia Comp VCA-65, dbx 165 : compresseur VCA."),
    (r"^comp tube-sta", "Arturia Comp TUBE-STA : compresseur à lampes vintage."),
    (r"^comp diode-609", "Arturia Comp DIODE-609, Neve 33609 : compresseur de bus à diodes."),
    (r"^delay tape-201", "Arturia Delay TAPE-201, Roland RE-201 Space Echo : écho à bande + ressort (dub)."),
    (r"^delay brigade", "Arturia Delay BRIGADE : délai analogique bucket-brigade (Memory Man)."),
    (r"^delay eternity", "Arturia Delay ETERNITY : délai créatif modulé."),
    (r"^chorus jun-6", "Arturia Chorus JUN-6 : le chorus du Juno-6 (élargir pads et basses)."),
    (r"^chorus dimension", "Arturia Chorus DIMENSION-D : Roland Dimension D (élargissement subtil)."),
    (r"^dist ", "Arturia Dist : distorsion/saturation (Coldfire, Opamp-21, Tube-Culture)."),
    (r"^bus force", "Arturia Bus FORCE : traitement de bus multi-modules (saturation, compression, EQ)."),
    (r"^bus peak", "Arturia Bus PEAK : limiteur de mastering."),
    (r"^bus exciter", "Arturia Bus EXCITER-104, excitateur (Aphex) : brillance, présence."),
    (r"^bus transient", "Arturia Bus TRANSIENT : modeleur de transitoires."),
    (r"^efx ", "Arturia Efx : effets créatifs (Fragments granulaire, Motions, Refract, Ambient)."),
    (r"^rev |^reverb", "Réverbe (Arturia Rev PLATE-140 = plaque EMT 140, SPRING-636 = ressort, INTENSITY...)."),
    (r"^pre |^eq ", "Préampli / EQ de console vintage (Arturia Pre 1973 = Neve 1073, etc.)."),
    (r"^filter ", "Arturia Filter : filtres de synthés vintage (Mini, M12, SEM, MS-20) en effet."),
    (r"cthulhu", "Xfer Cthulhu, mémoire d'accords + arpégiateur (MIDI) : un doigt joue des accords."),
    (r"chordjam", "Chordjam : générateur d'accords et de mélodies (MIDI)."),
    (r"seqund", "510k Seqund : séquenceur pas à pas / générateur (MIDI)."),
    (r"overbridge|elektron|analog (rytm|four|heat)|digitakt|digitone|syntakt|overbridge",
     "Elektron Overbridge : intégration des machines Elektron (audio multipiste + paramètres) dans Live."),
    (r"elevate|saturate|punctuate|generate|equivocate|kotelnikov", "Newfangled Audio : mastering et création (Elevate limiteur/EQ, Saturate, Generate synthé)."),
    (r"^bx_|brainworx|plugin alliance|spl |shadow hills|lindell|black box|ampeg|maag",
     "Plugin Alliance : émulations de mixage/mastering (Brainworx, SPL, Maag...)."),
    (r"serum", "Xfer Serum : synthé wavetable (basses et leads EDM)."),
    (r"diva", "u-he Diva : synthé analogique virtuel très réaliste."),
    (r"valhalla", "Valhalla : réverbes et délais (VintageVerb, Supermassive...)."),
    (r"fabfilter|pro-q|pro-c|pro-l|saturn|timeless", "FabFilter : EQ, compression, limiteur, saturation de référence."),
    (r"soundtoys|decapitator|echoboy", "Soundtoys : saturation et délais à caractère."),
    (r"^au[a-z]", "Apple AU : effets et instruments AU intégrés à macOS."),
]

KIND_BY_CLASS = {
    "PluginDevice": "plug-in VST/VST3", "AuPluginDevice": "plug-in Audio Unit",
    "MxDeviceAudioEffect": "Max for Live (effet audio)", "MxDeviceInstrument": "Max for Live (instrument)",
    "MxDeviceMidiEffect": "Max for Live (effet MIDI)", "InstrumentGroupDevice": "rack d'instruments",
    "AudioEffectGroupDevice": "rack d'effets audio", "MidiEffectGroupDevice": "rack d'effets MIDI",
    "DrumGroupDevice": "Drum Rack",
}


def plugin_description(name: str) -> Optional[str]:
    low = (name or "").lower().strip()
    for pattern, text in PLUGINS:
        if re.search(pattern, low):
            return text
    return None


def lookup(name: str) -> Optional[Dict]:
    """Native device by Live's display name (case-insensitive), else a
    plug-in family, else None."""
    low = (name or "").strip().lower()
    for key, entry in NATIVE.items():
        if key.lower() == low:
            source = "Ableton Pack (Max for Live)" if key in PACK_DEVICES else "Ableton Live 12 manual"
            return dict(entry, name=key, source=source)
    text = plugin_description(name)
    if text:
        return {"name": name, "kind": "plug-in", "what": text, "source": "plug-in family"}
    return None


def describe_device(dev: Dict) -> Dict:
    """Short card for an inventory entry ({name, class_name, class_display_name})."""
    cls = dev.get("class_name") or ""
    display = dev.get("class_display_name") or ""
    kind = KIND_BY_CLASS.get(cls)
    card = {"preset_or_name": dev.get("name"), "device": display or cls, "class_name": cls}
    entry = lookup(display) or lookup(dev.get("name", ""))
    if cls in ("PluginDevice", "AuPluginDevice"):
        card["kind"] = kind
        card["what"] = plugin_description(dev.get("name", "")) or plugin_description(display) or \
            "Plug-in tiers (fonction à déduire de ses paramètres ou de sa documentation)."
        return card
    if cls.startswith("MxDevice"):
        card["kind"] = kind
        e = lookup(dev.get("name", "")) or lookup(display)
        card["what"] = e["what"] if e else "Device Max for Live (voir son interface ou sa documentation)."
        return card
    if entry:
        card.update({"kind": kind or entry.get("kind"), "category": entry.get("category"), "what": entry["what"],
                     "key_parameters": entry.get("key_parameters"), "electronic_uses": entry.get("electronic_uses")})
        if entry.get("sidechain"):
            card["sidechain"] = True
    else:
        card["kind"] = kind or "device natif"
        card["what"] = "Device natif de Live (pas de fiche détaillée)."
    return card


def catalog(kind: Optional[str] = None) -> List[Dict]:
    out = []
    for key, e in NATIVE.items():
        if kind and e["kind"] != kind:
            continue
        out.append({"name": key, "kind": e["kind"], "category": e["category"], "what": e["what"]})
    return out
