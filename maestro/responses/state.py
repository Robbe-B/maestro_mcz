class State:
    vel_imp_ventola_fumi: int
    vel_real_ventola_fumi: int
    vel_imp_coclea: int
    vel_real_coclea: int
    pressione: int
    pressione_imp: int
    temp_scheda: float
    index_vel_v1: int
    index_vel_v2: int
    index_vel_v3: int
    potenza_att: int
    potenza_counter: int
    t_dur_pul: int
    t_int_pul: int
    state: str
    state_duration: int
    temp_fumi: int
    mode: str
    crono_enabled: bool
    att_eco: bool
    pul_brac: bool
    ingr_amb: int
    sens_liv_pellet: bool
    nome_banca_dati_sel: str
    adaptive_on: bool
    last_alarm: str
    set_amb1: float
    temp_amb_install: float
    status_timestamp: int
    last_stdt: int
    site_time_zone: str
    blocking_event_id: None
    description: str
    is_connected: bool
    is_in_error: bool

    def __init__(self, json) -> None:
        self.vel_imp_ventola_fumi = json["vel_imp_ventola_fumi"]
        self.vel_real_ventola_fumi = json["vel_real_ventola_fumi"]
        self.vel_imp_coclea = json["vel_imp_coclea"]
        self.vel_real_coclea = json["vel_real_coclea"]
        self.pressione = json["pressione"]
        self.pressione_imp = json["pressione_imp"]
        self.temp_scheda = json["temp_scheda"]
        self.index_vel_v1 = json["index_vel_v1"]
        self.index_vel_v2 = json["index_vel_v2"]
        self.index_vel_v3 = json["index_vel_v3"]
        self.potenza_att = json["potenza_att"]
        self.potenza_counter = json["potenza_counter"]
        self.t_dur_pul = json["t_dur_pul"]
        self.t_int_pul = json["t_int_pul"]
        self.state = json["state"]
        self.state_duration = json["state_duration"]
        self.temp_fumi = json["temp_fumi"]
        self.mode = json["mod_lav_att"]
        self.crono_enabled = json["crono_enabled"]
        self.att_eco = json["att_eco"]
        self.pul_brac = json["pul_brac"]
        self.ingr_amb = json["ingr_amb"]
        self.sens_liv_pellet = json["sens_liv_pellet"]
        self.nome_banca_dati_sel = json["nome_banca_dati_sel"]
        self.adaptive_on = json["adaptive_on"]
        self.last_alarm = json["last_alarm"]
        self.set_amb1 = json["set_amb1"]
        self.temp_amb_install = json["temp_amb_install"]
        self.status_timestamp = json["StatusTimestamp"]
        self.last_stdt = json["LastSTDT"]
        self.site_time_zone = json["SiteTimeZone"]
        self.blocking_event_id = json["BlockingEventId"]
        self.description = json["Description"]
        self.is_connected = json["IsConnected"]
        self.is_in_error = json["IsInError"]