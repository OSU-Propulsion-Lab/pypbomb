# -*- coding: utf-8 -*-
"""
PURPOSE:
    Thermochemical calculations

CREATED BY:
    Mick Carter
    Oregon State University
    CIRE and Propulsion Lab
    cartemic@oregonstate.edu
"""

import cantera as ct
import numpy as np
import pint

from . import tools, sd


_U = pint.UnitRegistry()


def calculate_laminar_flame_speed(
        initial_temperature,
        initial_pressure,
        species_dict,
        mechanism,
        phase_specification="",
        unit_registry=_U
):
    """
    This function uses cantera to calculate the laminar flame speed of a given
    gas mixture.

    Parameters
    ----------
    initial_temperature : pint.Quantity
        Initial temperature of gas mixture
    initial_pressure : pint.Quantity
        Initial pressure of gas mixture
    species_dict : dict
        Dictionary with species names (all caps) as keys and moles as values
    mechanism : str
        String of mechanism to use (e.g. "gri30.cti")
    phase_specification : str
        Phase specification for cantera solution
    unit_registry : pint.UnitRegistry
        Unit registry for managing units to prevent conflicts with parent
        unit registry

    Returns
    -------
    pint.Quantity
        Laminar flame speed in m/s as a pint quantity
    """
    gas = ct.Solution(mechanism, phase_specification)
    quant = unit_registry.Quantity

    tools.check_pint_quantity(
        initial_pressure,
        "pressure",
        ensure_positive=True
    )
    tools.check_pint_quantity(
        initial_temperature,
        "temperature",
        ensure_positive=True
    )

    # ensure species dict isn't empty
    if len(species_dict) == 0:
        raise ValueError("Empty species dictionary")

    # ensure all species are in the mechanism file
    bad_species = ""
    good_species = gas.species_names
    for species in species_dict:
        if species not in good_species:
            bad_species += species + "\n"
    if len(bad_species) > 0:
        raise ValueError("Species not in mechanism:\n" + bad_species)

    gas.TPX = (
        initial_temperature.to("K").magnitude,
        initial_pressure.to("Pa").magnitude,
        species_dict
    )

    # find laminar flame speed
    flame = ct.FreeFlame(gas)
    flame.set_refine_criteria(ratio=3, slope=0.1, curve=0.1)
    flame.solve(loglevel=0)

    return quant(flame.u[0], "m/s")


# noinspection SpellCheckingInspection
def get_eq_sound_speed(
        temperature,
        pressure,
        species_dict,
        mechanism,
        phase_specification="",
        unit_registry=_U
):
    """
    Calculates the equilibrium speed of sound in a mixture

    Parameters
    ----------
    temperature : pint.Quantity
        Initial mixture temperature
    pressure : pint.Quantity
        Initial mixture pressure
    species_dict : dict
        Dictionary of mixture mole fractions
    mechanism : str
        Desired chemical mechanism
    phase_specification : str
        Phase specification for cantera solution
    unit_registry : pint.UnitRegistry
        Unit registry for managing units to prevent conflicts with parent
        unit registry

    Returns
    -------
    sound_speed : pint.Quantity
        local speed of sound in m/s
    """
    quant = unit_registry.Quantity

    tools.check_pint_quantity(
        pressure,
        "pressure",
        ensure_positive=True
    )

    tools.check_pint_quantity(
        temperature,
        "temperature",
        ensure_positive=True
    )

    working_gas = ct.Solution(mechanism, phase_specification)
    working_gas.TPX = [
        temperature.to("K").magnitude,
        pressure.to("Pa").magnitude,
        species_dict
        ]

    pressures = np.zeros(2)
    densities = np.zeros(2)

    # equilibrate gas at input conditions and collect pressure, density
    working_gas.equilibrate("TP")
    pressures[0] = working_gas.P
    densities[0] = working_gas.density

    # perturb pressure and equilibrate with constant P, s to get dp/drho|s
    pressures[1] = 1.0001 * pressures[0]
    working_gas.SP = working_gas.s, pressures[1]
    working_gas.equilibrate("SP")
    densities[1] = working_gas.density

    # calculate sound speed
    sound_speed = np.sqrt(np.diff(pressures)/np.diff(densities))[0]

    return quant(sound_speed, "m/s")


def calculate_reflected_shock_state(
        initial_temperature,
        initial_pressure,
        species_dict,
        mechanism,
        unit_registry=_U,
        use_multiprocessing=False
):
    """
    Calculates the thermodynamic and chemical state of a reflected shock
    using customized sdtoolbox functions.

    Parameters
    ----------
    initial_temperature : pint.Quantity
        Pint quantity of mixture initial temperature
    initial_pressure : pint.Quantity
        Pint quantity of mixture initial pressure
    species_dict : dict
        Dictionary of initial reactant mixture
    mechanism : str
        Mechanism to use for chemical calculations, e.g. "gri30.cti"
    unit_registry : pint.UnitRegistry
        Pint unit registry
    use_multiprocessing : bool
        True to use multiprocessing for CJ state calculation, which is faster
        but requires the function to be run from __main__

    Returns
    -------
    dict
        Dictionary containing keys "reflected" and "cj". Each of these
        contains "speed", indicating the related wave speed, and "state",
        which is a Cantera gas object at the specified state.
    """
    quant = unit_registry.Quantity

    # define gas objects
    initial_gas = ct.Solution(mechanism)
    reflected_gas = ct.Solution(mechanism)

    # define gas states
    initial_temperature = initial_temperature.to("K").magnitude
    initial_pressure = initial_pressure.to("Pa").magnitude

    initial_gas.TPX = [
        initial_temperature,
        initial_pressure,
        species_dict
    ]
    reflected_gas.TPX = [
        initial_temperature,
        initial_pressure,
        species_dict
    ]

    # get CJ state
    cj_calcs = sd.Detonation.cj_speed(
        initial_pressure,
        initial_temperature,
        species_dict,
        mechanism,
        return_state=True,
        use_multiprocessing=use_multiprocessing
    )

    # get reflected state
    [_,
     reflected_speed,
     reflected_gas] = sd.Reflection.reflect(
        initial_gas,
        cj_calcs["cj state"],
        reflected_gas,
        cj_calcs["cj speed"]
    )

    return {
        "reflected": {
            "speed": quant(
                reflected_speed,
                "m/s"
            ),
            "state": reflected_gas
        },
        "cj": {
            "speed": quant(
                cj_calcs["cj speed"],
                "m/s"),
            "state": cj_calcs["cj state"]
        }
    }


class Mixture:
    def __init__(
            self,
            initial_pressure,
            initial_temperature,
            fuel,
            oxidizer,
            diluent=None,
            equivalence=1,
            diluent_mole_fraction=0,
            mechanism="gri30.cti",
            unit_registry=_U
    ):
        """ TODO: docstring updates

        Parameters
        ----------
        initial_pressure
        initial_temperature
        fuel
        oxidizer
        diluent
        equivalence
        diluent_mole_fraction
        mechanism
        unit_registry
        """
        self._quant = unit_registry.Quantity

        tools.check_pint_quantity(
            initial_pressure,
            "pressure",
            ensure_positive=True
        )

        tools.check_pint_quantity(
            initial_temperature,
            "temperature",
            ensure_positive=True
        )

        # initialize diluted and undiluted gas solution in Cantera
        self.undiluted = ct.Solution(mechanism)
        self.undiluted.TP = (
            initial_temperature.to("degK").magnitude,
            initial_pressure.to("Pa").magnitude
        )

        # make sure the user input species that are in the mechanism file
        good_species = self.undiluted.species_names
        if fuel in good_species:
            self.fuel = fuel
        else:
            raise ValueError("Bad fuel")
        if oxidizer in good_species:
            self.oxidizer = oxidizer
        else:
            raise ValueError("Bad oxidizer")
        if (diluent and diluent in good_species) or not diluent:
            self.diluent = diluent
        else:
            raise ValueError("Bad diluent")

        # define givens
        self.mechanism = mechanism
        self.initial_pressure = self._quant(
            initial_pressure.magnitude,
            initial_pressure.units.format_babel()
        ).to_base_units()
        self.initial_temperature = self._quant(
            initial_temperature.magnitude,
            initial_temperature.units.format_babel()
        ).to_base_units()
        self.diluent_mol_fraction = diluent_mole_fraction

        # set equivalence ratio
        self.equivalence = None
        self.set_equivalence(equivalence)

        # initialize diluted gas solution if diluent and mass fraction are
        # defined
        if diluent and diluent_mole_fraction:
            self.diluted = ct.Solution(mechanism)
            self.diluted.TP = (
                self.initial_temperature.to("degK").magnitude,
                self.initial_pressure.to("Pa").magnitude
            )
        else:
            self.diluted = None

    def set_equivalence(
            self,
            equivalence_ratio
    ):
        """
        Sets the equivalence ratio of both the undiluted and diluted mixtures
        using Cantera and Mixture.add_diluent

        Parameters
        ----------
        equivalence_ratio : float
            New mixture equivalence ratio

        Returns
        -------
        None
        """
        equivalence_ratio = float(equivalence_ratio)

        # set the equivalence ratio
        self.undiluted.set_equivalence_ratio(equivalence_ratio,
                                             self.fuel,
                                             self.oxidizer)
        if self.diluent and self.diluent_mol_fraction:
            self.add_diluent(self.diluent, self.diluent_mol_fraction)

        self.equivalence = equivalence_ratio

    def add_diluent(
            self,
            diluent,
            mole_fraction
    ):
        """ TODO: docstring updates
        Adds a diluent to an undiluted mixture, keeping the same equivalence
        ratio.
        """
        # make sure diluent is available in mechanism and isn't the fuel or ox
        if diluent in [self.fuel, self.oxidizer]:
            raise ValueError("You can\'t dilute with fuel or oxidizer!")
        elif diluent not in self.undiluted.species_names:
            if len(diluent.split(" ")) > 1:
                _check_compound_component(
                    diluent,
                    self.undiluted.species_names
                )
            else:
                raise ValueError("Bad diluent: {}".format(diluent))

        if mole_fraction > 1. or mole_fraction < 0:
            raise ValueError("Bro, do you even mole fraction?")

        self.diluent = diluent
        self.diluent_mol_fraction = mole_fraction

        # collect undiluted mole fractions
        mole_fractions = self.undiluted.mole_fraction_dict()

        # create cantera solution if one doesn't exist
        self.diluted = ct.Solution(self.mechanism)
        new_species = _diluted_species_dict(
                mole_fractions,
                diluent,
                mole_fraction
            )
        self.diluted.TPX = (
            self.initial_temperature.to('degK').magnitude,
            self.initial_pressure.to('Pa').magnitude,
            new_species
        )

    def get_masses(
            self,
            tube_volume,
            diluted=False
    ):
        """
        The cantera concentration function is used to collect
        species concentrations, in kmol/m^3, which are then multiplied by
        the molecular weights in kg/kmol to get the density in kg/m^3. This
        is then multiplied by the tube volume to get the total mass of each
        component.

        Parameters
        ----------
        tube_volume : pint.Quantity
            Total volume of the reactant mixture
        diluted : bool
            True to use the diluted mixture, False to use the undiluted mixture

        Returns
        -------
        dict
            Dictionary of component masses within the reactant mixture
        """
        tools.check_pint_quantity(
            tube_volume,
            "volume",
            ensure_positive=True
        )

        tube_volume = self._quant(
            tube_volume.magnitude,
            tube_volume.units.format_babel()
        )

        if diluted and self.diluted is None:
            raise ValueError("Mixture has not been diluted")
        elif diluted:
            cantera_solution = self.diluted
        else:
            cantera_solution = self.undiluted
        mixture_list = []
        for i, species in enumerate(cantera_solution.species_names):
            if cantera_solution.X[i] > 0:
                r_specific = self._quant(
                    8314 / cantera_solution.molecular_weights[i],
                    "J/(kg*K)"
                )
                pressure = self.initial_pressure * cantera_solution.X[i]
                rho = pressure / (r_specific * self.initial_temperature)
                mixture_list.append((species, (rho * tube_volume).to("kg")))

        return dict(mixture_list)

    def get_pressures(
            self,
            diluted=False
    ):
        """ TODO: docstring updates
        Cantera is used to get the mole fractions of each species, which are
        then multiplied by the initial pressure to get each partial pressure.
        """
        if diluted and self.diluted is None:
            raise ValueError("Mixture has not been diluted")
        elif diluted:
            cantera_solution = self.diluted
        else:
            cantera_solution = self.undiluted
        mixture_list = []
        for i, species in enumerate(cantera_solution.species_names):
            if cantera_solution.X[i] > 0:
                mixture_list.append((species,
                                    self.initial_pressure *
                                    cantera_solution.X[i]))
        return dict(mixture_list)


def _check_compound_component(
        component,
        species_names
):
    """
    Check to make sure each constituent part of a compound component (e.g.
    "O2:1 N2:3.76" for air) is within a given mechanism

    Parameters
    ----------
    component : str
        Compound component string (e.g. "O2:1 N2:3.76")
    species_names : List[String]
        List of species within the desired mechanism to check against

    Returns
    -------
    None
    """
    species = component.split(" ")
    for s in species:
        s = s.split(":")[0]
        if s not in species_names:
            raise ValueError("{:s} not a valid species".format(s))


def _diluted_species_dict(
        spec,
        diluent,
        diluent_mol_frac
):
    """
    Creates a dictionary of mole fractions diluted by a given amount with a
    given gas mixture

    Parameters
    ----------
    spec : dict
        Mole fraction dictionary (gas.mole_fraction_dict() from undiluted)
    diluent : str
        String of diluents using cantera's format, e.g. "CO2" or "N2:1 NO:0.01"
    diluent_mol_frac : float
        mole fraction of diluent to add

    Returns
    -------
    dict
        new mole_fraction_dict to be inserted into the cantera solution object
    """
    # collect total diluent moles
    moles_dil = 0.
    diluent_dict = dict()
    split_diluents = diluent.split(" ")
    if len(split_diluents) > 1:
        for d in split_diluents:
            key, value = d.split(":")
            value = float(value)
            diluent_dict[key] = value
            moles_dil += value
    else:
        diluent_dict[diluent] = 1
        moles_dil = 1

    for key in diluent_dict.keys():
        diluent_dict[key] /= moles_dil

    for key, value in diluent_dict.items():
        if key not in spec.keys():
            spec[key] = 0

        if diluent_mol_frac != 0:
            spec[key] += diluent_dict[key] / (1 / diluent_mol_frac - 1)

    new_total_moles = sum(spec.values())
    for s in spec.keys():
        spec[s] /= new_total_moles
    return spec
