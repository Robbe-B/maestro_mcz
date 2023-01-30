class Status:
    status: str
    stato_stufa: int
    turbo_activation_timestamp: int
    scheduled_turn_off_timestamp: int
    is_crono_empty: bool
    is_ble_connected: bool
    sm_nome_app: str
    sm_vs_app: int
    mc_vs_app: str
    fase_op: str
    sub_fase_op: str
    mod_lav_att: str
    set_pot_man: int
    set_amb1: float
    set_amb2: float
    set_amb3: float
    set_vent_v1: int
    set_vent_v2: int
    set_vent_v3: int
    v_ven1_v0: int
    v_ven2_v0: int
    v_ven3_v0: int
    potenza_att: int
    index_vel_v1: int
    index_vel_v2: int
    index_vel_v3: int
    temp_amb_can1: float
    temp_amb_can2: float
    temp_amb_can3: float
    temp_amb_install: float
    wifi_status: int
    silent_enabled: bool
    crono_enabled: bool
    sleep_enabled: bool
    clean_air_in_prog: bool
    clean_in_prog: bool
    power_enabled: bool
    silent: bool
    t_power: int
    att_eco: bool
    sens_liv_pellet: bool
    auto_pellet: int
    sens_liv_pel: bool
    pul_brac: bool
    ingr_amb: int
    rit_usc_standby: int
    rit_ing_standby: int
    ist_neg_amb: float
    ist_pos_amb: float
    ist_eco_neg_amb: float
    ist_eco_pos_amb: float
    com_es_car_coclea: bool
    t_car_pel_man: int
    pos_ric_pel: int
    pos_ric_flu: int
    anno: int
    mese: int
    giorno: int
    ore: int
    minuti: int
    secondi: int
    giorno_sett: int
    am_pm: bool
    pressione_pascal: int
    pressione: int
    pressione_imp: int
    act: bool
    act_acc: bool
    ore_prox_manut: int
    toni_buzz: int
    mod_ada_on: bool
    ssid_wifi: str
    sm_sn: str
    nome_banca_dati_sel: str
    cont_fine_pul: bool
    ing_term_amb1: bool
    description: str
    is_connected: bool
    is_in_error: bool
    status_timestamp: int
    last_stdt: int
    site_time_zone: str
    blocking_event_id: None

    def __init__(self, json) -> None:
        self.status = json["Status"]
        self.stato_stufa = json["stato_stufa"]
        self.turbo_activation_timestamp = json["TurboActivationTimestamp"]
        self.scheduled_turn_off_timestamp = json["ScheduledTurnOffTimestamp"]
        self.is_crono_empty = json["IsCronoEmpty"]
        self.is_ble_connected = json["IsBLEConnected"]
        self.sm_nome_app = json["sm_nome_app"]
        self.sm_vs_app = json["sm_vs_app"]
        self.mc_vs_app = json["mc_vs_app"]
        self.fase_op = json["fase_op"]
        self.sub_fase_op = json["sub_fase_op"]
        self.mod_lav_att = json["mod_lav_att"]
        self.set_pot_man = json["set_pot_man"]
        self.set_amb1 = json["set_amb1"]
        self.set_amb2 = json["set_amb2"]
        self.set_amb3 = json["set_amb3"]
        self.set_vent_v1 = json["set_vent_v1"]
        self.set_vent_v2 = json["set_vent_v2"]
        self.set_vent_v3 = json["set_vent_v3"]
        self.v_ven1_v0 = json["v_ven1_v0"]
        self.v_ven2_v0 = json["v_ven2_v0"]
        self.v_ven3_v0 = json["v_ven3_v0"]
        self.potenza_att = json["potenza_att"]
        self.index_vel_v1 = json["index_vel_v1"]
        self.index_vel_v2 = json["index_vel_v2"]
        self.index_vel_v3 = json["index_vel_v3"]
        self.temp_amb_can1 = json["temp_amb_can1"]
        self.temp_amb_can2 = json["temp_amb_can2"]
        self.temp_amb_can3 = json["temp_amb_can3"]
        self.temp_amb_install = json["temp_amb_install"]
        self.wifi_status = json["wifi_status"]
        self.silent_enabled = json["silent_enabled"]
        self.crono_enabled = json["crono_enabled"]
        self.sleep_enabled = json["sleep_enabled"]
        self.clean_air_in_prog = json["clean_air_in_prog"]
        self.clean_in_prog = json["clean_in_prog"]
        self.power_enabled = json["power_enabled"]
        self.silent = json["silent"]
        self.t_power = json["t_power"]
        self.att_eco = json["att_eco"]
        self.sens_liv_pellet = json["sens_liv_pellet"]
        self.auto_pellet = json["auto_pellet"]
        self.sens_liv_pel = json["sens_liv_pel"]
        self.pul_brac = json["pul_brac"]
        self.ingr_amb = json["ingr_amb"]
        self.rit_usc_standby = json["rit_usc_standby"]
        self.rit_ing_standby = json["rit_ing_standby"]
        self.ist_neg_amb = json["ist_neg_amb"]
        self.ist_pos_amb = json["ist_pos_amb"]
        self.ist_eco_neg_amb = json["ist_eco_neg_amb"]
        self.ist_eco_pos_amb = json["ist_eco_pos_amb"]
        self.com_es_car_coclea = json["com_es_car_coclea"]
        self.t_car_pel_man = json["t_car_pel_man"]
        self.pos_ric_pel = json["pos_ric_pel"]
        self.pos_ric_flu = json["pos_ric_flu"]
        self.anno = json["anno"]
        self.mese = json["mese"]
        self.giorno = json["giorno"]
        self.ore = json["ore"]
        self.minuti = json["minuti"]
        self.secondi = json["secondi"]
        self.giorno_sett = json["giorno_sett"]
        self.am_pm = json["am_pm"]
        self.pressione_pascal = json["pressione_pascal"]
        self.pressione = json["pressione"]
        self.pressione_imp = json["pressione_imp"]
        self.act = json["act"]
        self.act_acc = json["act_acc"]
        self.ore_prox_manut = json["ore_prox_manut"]
        self.toni_buzz = json["toni_buzz"]
        self.mod_ada_on = json["mod_ada_on"]
        self.ssid_wifi = json["SSID_wifi"]
        self.sm_sn = json["sm_sn"]
        self.nome_banca_dati_sel = json["nome_banca_dati_sel"]
        self.cont_fine_pul = json["cont_fine_pul"]
        self.ing_term_amb1 = json["ing_term_amb1"]
        self.description = json["Description"]
        self.is_connected = json["IsConnected"]
        self.is_in_error = json["IsInError"]
        self.status_timestamp = json["StatusTimestamp"]
        self.last_stdt = json["LastSTDT"]
        self.site_time_zone = json["SiteTimeZone"]
        self.blocking_event_id = json["BlockingEventId"]
