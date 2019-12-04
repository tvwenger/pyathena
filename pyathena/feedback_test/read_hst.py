# read_hst.py

import os
import numpy as np
import pandas as pd
import astropy.constants as ac
import astropy.units as au

from ..io.read_hst import read_hst
from ..load_sim import LoadSim

class ReadHst:

    @LoadSim.Decorators.check_pickle_hst
    def read_hst(self, savdir=None, force_override=False):
        """Function to read hst and convert quantities to convenient units
        """

        hst = read_hst(self.files['hst'], force_override=force_override)

        u = self.u
        domain = self.domain
        # volume of resolution element (code unit)
        dvol = domain['dx'].prod()
        # total volume of domain (code unit)
        vol = domain['Lx'].prod()        

        # Time in code unit
        hst['time_code'] = hst['time']
        # Time in Myr
        hst['time'] *= u.Myr
        # Total gas mass in Msun
        hst['mass'] *= vol*u.Msun

        # Shell formation time in Myr (Eq.7 in Kim & Ostriker 2015)
        tsf = 4.4e-2*self.par['problem']['n0']**-0.55
        hst['time_tsf'] = hst['time']/tsf
        hst['tsf'] = tsf

        # Mass weighted SNR position in pc
        hst['Rsh'] = hst['Rsh_den']/hst['Msh']*u.pc
        # shell mass in Msun
        hst['Msh'] *= u.Msun*vol
        # hot gas mass in Msun
        hst['Mhot'] *= u.Msun*vol
        # warm gas mass in Msun
        hst['Mwarm'] *= u.Msun*vol
        # intermediate temperature gas in Msun
        hst['Minter'] *= u.Msun*vol
        # cold gas mass in Msun
        hst['Mcold'] *= u.Msun*vol

        # Total/hot gas/shell momentum in Msun*km/s
        hst['pr'] *= vol*(u.mass*u.velocity).value
        hst['pr_hot'] *= vol*(u.mass*u.velocity).value
        hst['pr_sh'] *= vol*(u.mass*u.velocity).value

        # Predicted momentum
        from scipy.integrate import cumtrapz

        hst['pr_pred'] = cumtrapz(hst['Ltot0']/ac.c.to(u.velocity).value,
                                  hst['time_code'], initial=0.0)
        
        hst['pr_pred'] *= vol*(u.mass*u.velocity).value
        
        # Total/escaping luminosity in Lsun
        nfreq = self.par['radps']['nfreq']
        try:
            for i in range(nfreq):
                hst['Ltot{0:d}'] *= vol*u.Lsun
                hst['Lesc{0:d}'] *= vol*u.Lsun
        except KeyError:
            pass
        
        hst.index = hst['time_code']
        
        self.hst = hst
        
        return hst