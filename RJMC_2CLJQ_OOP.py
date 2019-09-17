#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Code that performs RJMC simulation between UA,AUA, and AUA+Q subsets of the
2CLJQ model using analytical surrogate models.
"""


from __future__ import division
import numpy as np
import argparse
import scipy as sp
import matplotlib.pyplot as plt
import pandas as pd
import yaml
from LennardJones_correlations import LennardJones
from LennardJones_2Center_correlations import LennardJones_2C
from scipy.stats import distributions
from scipy.stats import linregress
from scipy.optimize import minimize
import random as rm
from pymc3.stats import hpd
from RJMC_auxiliary_functions import *
from datetime import date
import copy
from pymbar import BAR,timeseries
import random
import sys
import os
from shutil import rmtree
import math



class RJMC_Simulation():
    """ Builds an object that runs an RJMC simulation based on the parameters the user gives to it
    
    
    Attributes:
        
        
    """
    
    def __init__(self,compound,T_range,properties,n_points,steps,swap_freq,biasing_factor,optimum_matching,tune_freq=100,tune_for=10000):
        """Initializes the basic state of the simulator object.
        
        Parameters
        ----------
        data_physical_state: dict
            Passes information about the physical state of the simulation, i.e. 
            which compound, what temperature range, which properties and how
            many data points
        steps: int
            Number of steps which the simulation should run for.
        swap_freq: float
            Percentage of times the simulation tries to jump between models
        biasing_factor: array
            Applies a biasing factor to a certain model
        prior: class
            Initializing priors for RJMC sampling
        """
        
        self.compound = compound
        self.T_range = T_range
        self.properties = properties
        self.n_points = n_points
        self.steps = steps
        self.swap_freq = swap_freq
        self.biasing_factor = biasing_factor
        self.optimum_matching = optimum_matching
        self.tune_for=tune_for
        self.tune_freq=tune_freq
        
        
    def get_attributes(self):
        """Return attributes of RJMC system
        """
        
        
        return {
            'compound': self.compound,
            'properties': self.properties,
            'T_range': self.T_range,
            'n_points': self.n_points,
            'steps': self.steps,
            'swap_freq': self.swap_freq,
            'biasing_factor': self.biasing_factor}
    
    
    
    def prepare_data(self):
        """From input parameters, pull appropriate experimental data and
        uncertainty information.
        """
        
        
        
        
        self.ff_params_ref,self.Tc_lit,self.M_w,thermo_data,self.NIST_bondlength=parse_data_ffs(self.compound)
        #Retrieve force field literature values, constants, and thermo data
        
        
    
    
        self.T_min = self.T_range[0]*self.Tc_lit[0]
        self.T_max = self.T_range[1]*self.Tc_lit[0]
        
        #Select temperature range of data points to select, and how many temperatures within that range to use data at. 
        
        thermo_data=filter_thermo_data(thermo_data,self.T_min,self.T_max,self.n_points)
        
        #Filter data to selected conditions.
        
        
        uncertainties=calculate_uncertainties(thermo_data,self.Tc_lit[0])
        #Calculate uncertainties for each data point, based on combination of experimental uncertainty and correlation uncertainty
        
        self.thermo_data_rhoL=np.asarray(thermo_data['rhoL'])
        self.thermo_data_Pv=np.asarray(thermo_data['Pv'])
        self.thermo_data_SurfTens=np.asarray(thermo_data['SurfTens'])
        #Convert dictionaries to numpy arrays
        
        
        # RJMC stuff
        
        # Calculate the estimated standard deviation
        sd_rhol = uncertainties['rhoL']/2.
        sd_Psat = uncertainties['Pv']/2.
        sd_SurfTens = uncertainties['SurfTens']/2
        
        # Calculate the precision in each property
        self.t_rhol = np.sqrt(1./sd_rhol)
        self.t_Psat = np.sqrt(1./sd_Psat)                                   
        self.t_SurfTens = np.sqrt(1./sd_SurfTens)

    def calc_posterior(self,prior,compound_2CLJ,chain_values):
        #def calc_posterior(model,eps,sig,L,Q,biasing_factor_UA=0,biasing_factor_AUA=0,biasing_factor_AUA_Q=0):
        
        dnorm = distributions.norm.logpdf
        
        
        
        logp = 0
        logp += prior.sigma_prior_function.logpdf(chain_values[2], *prior.sigma_prior_values)
        logp += prior.epsilon_prior_function.logpdf(chain_values[1], *prior.epsilon_prior_values)  
        #Create priors for parameters common to all models     
        if chain_values[0] == 2:
            chain_values[4]=0
            logp+=self.biasing_factor[2]
            #Ensure Q=0 for UA model
        
        elif chain_values[0] == 0:
            chain_values[4]=0
            logp+=prior.L_prior_function.logpdf(chain_values[3],*prior.L_prior_values)
            logp+=self.biasing_factor[0]
            #Add prior over L for AUA model
        
        elif chain_values[0] == 1:
            logp+=prior.Q_prior_function.logpdf(chain_values[4],*prior.Q_prior_values)
            logp+=prior.L_prior_function.logpdf(chain_values[3],*prior.L_prior_values)
            logp+=self.biasing_factor[1]
            #Add priors for Q and L for AUA+Q model
            
        rhol_hat = rhol_hat_models(compound_2CLJ,self.thermo_data_rhoL[:,0],*chain_values) #[kg/m3]
        Psat_hat = Psat_hat_models(compound_2CLJ,self.thermo_data_Pv[:,0],*chain_values) #[kPa]   
        SurfTens_hat = SurfTens_hat_models(compound_2CLJ,self.thermo_data_SurfTens[:,0],*chain_values)     
        #Compute properties at temperatures from experimental data
        
        
        # Data likelihood: Compute likelihood based on gaussian penalty function
        if self.properties == 'rhol':
            logp += sum(dnorm(self.thermo_data_rhoL[:,1],rhol_hat,self.t_rhol**-2.))
            #logp += sum(dnorm(rhol_data,rhol_hat,t_rhol**-2.))
        elif self.properties == 'Psat':
            logp += sum(dnorm(self.thermo_data_Pv[:,1],Psat_hat,self.t_Psat**-2.))
        elif self.properties == 'rhol+Psat':
            logp += sum(dnorm(self.thermo_data_rhoL[:,1],rhol_hat,self.t_rhol**-2.))
            logp += sum(dnorm(self.thermo_data_Pv[:,1],Psat_hat,self.t_Psat**-2.))
        elif self.properties == 'All':
             logp += sum(dnorm(self.thermo_data_rhoL[:,1],rhol_hat,self.t_rhol**-2.))
             logp += sum(dnorm(self.thermo_data_Pv[:,1],Psat_hat,self.t_Psat**-2.))           
             logp += sum(dnorm(self.thermo_data_SurfTens[:,1],SurfTens_hat,self.t_SurfTens**-2))
             
        return logp
                
    def set_initial_state(self,prior,compound_2CLJ,initial_model=None,initial_position=None):
        initial_logp=math.nan
        while math.isnan(initial_logp):       
            initial_values=np.empty(5)
            self.n_models=3
            
            rnorm=np.random.normal
            
            initial_values[0]=random.randint(0,self.n_models-1)
             
            
            if initial_model == 'AUA':
                initial_values[0] = 0
            elif initial_model == 'AUA+Q':
                initial_values[0] = 1
            elif initial_model == 'UA':
                initial_values[0] = 2
            
            if initial_values[0] == 0:
                initial_values[1] = rnorm(self.opt_params_AUA[0],self.opt_params_AUA[0]/10)
                initial_values[2] = rnorm(self.opt_params_AUA[1],self.opt_params_AUA[1]/10)
                initial_values[3] = rnorm(self.opt_params_AUA[2],self.opt_params_AUA[2]/10)
                initial_values[4] = 0
            elif initial_values[0] == 1:
                initial_values[1] = rnorm(self.opt_params_AUA_Q[0],self.opt_params_AUA_Q[0]/10)
                initial_values[2] = rnorm(self.opt_params_AUA_Q[1],self.opt_params_AUA_Q[1]/10)
                initial_values[3] = rnorm(self.opt_params_AUA_Q[2],self.opt_params_AUA_Q[2]/10)
                initial_values[4] = rnorm(self.opt_params_AUA_Q[2],self.opt_params_AUA_Q[2]/10)
            elif initial_values[0] == 2:
                initial_values[1] = rnorm(self.opt_params_UA[0],self.opt_params_UA[0]/10)
                initial_values[2] = rnorm(self.opt_params_UA[1],self.opt_params_UA[1]/10)
                initial_values[3] = self.NIST_bondlength
                initial_values[4] = 0
                
            if initial_position != None:
                initial_values=initial_position
            print('Markov Chain initialized at values:', initial_values)
            print('==============================')
            self.n_params=len(initial_values)
            self.prop_sd=np.asarray(initial_values)/100
            initial_logp = self.calc_posterior(prior,compound_2CLJ,initial_values)
            if math.isnan(initial_logp):
                print('Nan detected! Finding new values')
            
        print('Initial log posterior:', initial_logp)
        print('==============================')
        self.initial_values=initial_values
        self.initial_logp=initial_logp
        self.initial_percent_deviation=computePercentDeviations(compound_2CLJ,
                                               self.thermo_data_rhoL[:,0],
                                               self.thermo_data_Pv[:,0],
                                               self.thermo_data_SurfTens[:,0],
                                               self.initial_values,
                                               self.thermo_data_rhoL[:,1],
                                               self.thermo_data_Pv[:,1],
                                               self.thermo_data_SurfTens[:,1],
                                               self.Tc_lit[0],
                                               rhol_hat_models,
                                               Psat_hat_models,
                                               SurfTens_hat_models,
                                               T_c_hat_models)
        
    def gen_Tmatrix(self,prior,compound_2CLJ):
        ''' Generate Transition matrices based on the optimal eps, sig, Q for different models'''
        
        #Currently this is not used for moves between AUA and AUA+Q, because it doesn't seem to help.  Still used for UA and AUA moves
        
        obj_AUA = lambda eps_sig_Q: -self.calc_posterior(prior,compound_2CLJ,[0,eps_sig_Q[0],eps_sig_Q[1],eps_sig_Q[2],eps_sig_Q[3]])
        obj_AUA_Q = lambda eps_sig_Q: -self.calc_posterior(prior,compound_2CLJ,[1,eps_sig_Q[0],eps_sig_Q[1],eps_sig_Q[2],eps_sig_Q[3]])
        obj_2CLJ = lambda eps_sig_Q: -self.calc_posterior(prior,compound_2CLJ,[2,eps_sig_Q[0],eps_sig_Q[1],eps_sig_Q[2],eps_sig_Q[3]])
        
        
        guess_0 = [0,*self.ff_params_ref[1]]
        guess_1 = [1,*self.ff_params_ref[0]]
        guess_2 = [2,*self.ff_params_ref[2]]
        guess_2[3] = self.NIST_bondlength
        
        guess_AUA = [guess_0[1],guess_0[2],guess_0[3],guess_0[4]]
        guess_AUA_Q = [guess_1[1],guess_1[2],guess_1[3],guess_1[4]]
        guess_UA = [guess_2[1],guess_2[2],guess_2[3],guess_2[4]]
        
        # Make sure bounds are in a reasonable range so that models behave properly
        bnd_AUA = ((0.85*guess_AUA[0],guess_AUA[0]*1.15),(0.90*guess_AUA[1],guess_AUA[1]*1.1),(0.90*guess_AUA[2],guess_AUA[2]*1.1),(guess_AUA[3],guess_AUA[3]))
        bnd_AUA_Q = ((0.85*guess_AUA_Q[0],guess_AUA_Q[0]*1.15),(0.9*guess_AUA_Q[1],guess_AUA_Q[1]*1.1),(0.9*guess_AUA_Q[2],guess_AUA_Q[2]*1.1),(0.90*guess_AUA_Q[3],guess_AUA_Q[3]*1.1))
        bnd_UA = ((0.85*guess_UA[0],guess_UA[0]*1.15),(0.9*guess_UA[1],guess_UA[1]*1.1),(1*guess_UA[2],guess_UA[2]*1),(0.90*guess_UA[3],guess_UA[3]*1.1))
        #Help debug
    #    print(bnd_LJ)
    #    print(bnd_UA)
    #    print(bnd_AUA)
        
        
        opt_AUA = minimize(obj_AUA,guess_AUA,bounds=bnd_AUA)
        opt_AUA_Q = minimize(obj_AUA_Q,guess_AUA_Q,bounds=bnd_AUA_Q)
        opt_UA = minimize(obj_2CLJ,guess_UA,bounds=bnd_UA)
        #Help debug
    #    print(opt_LJ)
    #    print(opt_UA)
    #    print(opt_AUA)
            
        self.opt_params_AUA = opt_AUA.x[0],opt_AUA.x[1],opt_AUA.x[2],opt_AUA.x[3]
        self.opt_params_AUA_Q = opt_AUA_Q.x[0],opt_AUA_Q.x[1],opt_AUA_Q.x[2],opt_AUA_Q.x[3]
        self.opt_params_UA = opt_UA.x[0],opt_UA.x[1],opt_UA.x[2],opt_UA.x[3]

    def transition_function(self):
        
        unif = distributions.uniform.pdf
        
        transition_matrix=np.ones((self.n_models,self.n_models))
        g_0_1=unif(self.w,0,1)
        g_1_0=1
        g_0_2=1
        g_2_0=1
        #These are proposal distributions for "new" variables (that exist in one model but not the other).  They have been cleverly chosen to all equal 1
        
        
        q_0_1=1/2
        q_1_0=1
        q_0_2=1/2
        q_2_0=1
        #These are probabilities of proposing a model from one model to another.  
        #The probability is half for moves originating in AUA because they can move either to UA or AUA+Q. We disallow moves between UA and AUA+Q directly 
        
        #Note that this is really times swap_freq but that term always cancels.
        
        
        transition_matrix[0,1]=g_1_0*q_1_0/(g_0_1*q_0_1)
        transition_matrix[1,0]=g_0_1*q_0_1/(g_1_0*q_1_0)
        transition_matrix[0,2]=g_2_0*q_2_0/(g_0_2*q_0_2)
        transition_matrix[2,0]=g_0_2*q_0_2/(g_2_0*q_2_0)
        #Transition functions enumerated for each 
        
        
        return transition_matrix   
        
    def jacobian(self):
        jacobian_matrix=np.ones((self.n_models,self.n_models))
        
        if self.optimum_matching=='True':
            jacobian_matrix[0,1]=(1/(self.lamda*self.w))*(self.opt_params_AUA_Q[0]*self.opt_params_AUA_Q[1]*self.opt_params_AUA_Q[2])/(self.opt_params_AUA[0]*self.opt_params_AUA[1]*self.opt_params_AUA[2])
            jacobian_matrix[1,0]=self.lamda*(self.opt_params_AUA[0]*self.opt_params_AUA[1]*self.opt_params_AUA[2])/(self.opt_params_AUA_Q[0]*self.opt_params_AUA_Q[1]*self.opt_params_AUA_Q[2])
            jacobian_matrix[0,1]=1/(self.lamda*self.w)
            jacobian_matrix[1,0]=self.w*self.lamda
        else:
            jacobian_matrix[0,1]=1/(self.lamda*self.w)
            jacobian_matrix[1,0]=self.w*self.lamda
        
        #Optimum Matching for UA --> AUA
        #jacobian[0,1]=(1/(lamda*w))*(opt_params_AUA_Q[0]*opt_params_AUA_Q[1]*opt_params_AUA_Q[2])/(opt_params_AUA[0]*opt_params_AUA[1]*opt_params_AUA[2])
        #jacobian[1,0]=lamda*(opt_params_AUA[0]*opt_params_AUA[1]*opt_params_AUA[2])/(opt_params_AUA_Q[0]*opt_params_AUA_Q[1]*opt_params_AUA_Q[2])
        jacobian_matrix[0,2]=(self.opt_params_UA[0]*self.opt_params_UA[1]*self.opt_params_UA[2])/(self.opt_params_AUA[0]*self.opt_params_AUA[1]*self.opt_params_AUA[2])
        jacobian_matrix[2,0]=(self.opt_params_AUA[0]*self.opt_params_AUA[1]*self.opt_params_AUA[2])/(self.opt_params_UA[0]*self.opt_params_UA[1]*self.opt_params_UA[2])
        #Direct transfer for AUA->AUA+Q 

        
        
        
        return jacobian_matrix
    
    def RJMC_Outerloop(self,prior,compound_2CLJ):
        self.trace = [self.initial_values]
        self.logp_trace = [self.initial_logp]
        self.percent_dev_trace = [self.initial_percent_deviation]
        self.BAR_trace=[]
        self.move_proposals=np.zeros((self.n_models,self.n_models))
        self.move_acceptances=np.zeros((self.n_models,self.n_models))
        
        print('Initializing Simulation...')
        print('Tuning Proposals...')
        print('==============================')
        for i in range(self.steps+1):
            if not i%50000: print('Iteration '+str(i)),print('Log Posterior:',self.logp_trace[i])
            self.current_params = self.trace[i].copy()
            self.current_model = int(self.current_params[0])
            self.current_log_prob = self.logp_trace[i].copy()
        

        
        
            new_params,new_log_prob,acceptance=self.RJMC_Steps(prior,compound_2CLJ)
        
        
            self.move_proposals[int(self.current_params[0]),int(new_params[0])]+=1
        
            if acceptance == 'True':
                self.move_acceptances[int(self.current_params[0]),int(new_params[0])]+=1
        
        
                #accept_vector[i]=1
            self.logp_trace.append(new_log_prob)
            self.trace.append(new_params)
            self.percent_dev_trace.append(computePercentDeviations(compound_2CLJ,
                                                                         self.thermo_data_rhoL[:,0],
                                                                         self.thermo_data_Pv[:,0],
                                                                         self.thermo_data_SurfTens[:,0],
                                                                         self.trace[i+1],
                                                                         self.thermo_data_rhoL[:,1],
                                                                         self.thermo_data_Pv[:,1],
                                                                         self.thermo_data_SurfTens[:,1],self.Tc_lit[0],
                                                                         rhol_hat_models,
                                                                         Psat_hat_models,
                                                                         SurfTens_hat_models,
                                                                         T_c_hat_models))
            
            if (not (i+1) % self.tune_freq) and (i < self.tune_for):
                self.Tune_RJMC()
                
            if i == self.tune_for:
                self.move_proposals=np.zeros((self.n_models,self.n_models))
                self.move_acceptances=np.zeros((self.n_models,self.n_models))
                print('Tuning complete!')
                print('==============================')
        self.trace=np.asarray(self.trace)
        self.logp_trace=np.asarray(self.logp_trace)
        self.percent_dev_trace=np.asarray(self.percent_dev_trace)
        print('Simulation Done!')
        print('==============================')
    def RJMC_Steps(self,prior,compound_2CLJ):
        proposed_params=self.current_params.copy()
        
        random_move=np.random.random()
        
        
        if random_move <= self.swap_freq:
            proposed_params,proposed_log_prob,proposed_model,rjmc_jacobian,rjmc_transition=self.model_proposal(prior,proposed_params,compound_2CLJ)
            alpha = (proposed_log_prob - self.current_log_prob) + np.log(rjmc_jacobian) + np.log(rjmc_transition)
            self.BAR_trace.append([proposed_model,(proposed_log_prob - self.current_log_prob) + np.log(rjmc_jacobian)])
            
            
            if proposed_log_prob == math.nan:
                proposed_log_prob=-math.inf
                print('nan detected')
                
            
        else:
            proposed_params, proposed_log_prob=self.parameter_proposal(prior,proposed_params,compound_2CLJ)
            alpha = (proposed_log_prob - self.current_log_prob)


        acceptance=self.accept_reject(alpha)
        if acceptance == 'True':
            new_log_prob = proposed_log_prob
            new_params = proposed_params
        elif acceptance == 'False':
            new_log_prob = self.current_log_prob
            new_params = self.current_params
        
        return new_params,new_log_prob,acceptance
       
        
        
    def accept_reject(self,alpha):    
        urv=np.random.random()
        #Metropolis-Hastings accept/reject criteria
        if np.log(urv) < alpha:  
            acceptance='True'
        else: 
            acceptance='False'
        return acceptance


    def model_proposal(self,prior,proposed_params,compound_2CLJ):
        proposed_model=copy.deepcopy(self.current_model)
        
        #Propose new model to jump to
        while proposed_model==self.current_model:
            proposed_model=int(np.floor(np.random.random()*self.n_models))
            if proposed_model==2 and self.current_model==1:
                proposed_model=copy.deepcopy(self.current_model)
            elif proposed_model==1 and self.current_model==2:
                proposed_model=copy.deepcopy(self.current_model)
        self.lamda=5
        proposed_params[0] = proposed_model
        self.w=1
        
        proposed_params=self.model_transition(proposed_model,proposed_params)
       
    
        proposed_log_prob=self.calc_posterior(prior,compound_2CLJ,proposed_params)
        jacobian_matrix =  self.jacobian()
        rjmc_jacobian=jacobian_matrix[self.current_model,proposed_model]
        transition_matrix=self.transition_function()
        rjmc_transition=transition_matrix[self.current_model,proposed_model]
        #Return values of jacobian in order to properly calculate accept/reject
        return proposed_params,proposed_log_prob,proposed_model,rjmc_jacobian,rjmc_transition
    
    def model_transition(self,proposed_model,proposed_params):
        if proposed_model==1 and self.current_model==0:
            
            #AUA ---> AUA+Q
            if self.optimum_matching[0] =='True':
                
            #Optimum Matching
                proposed_params[1] = (self.opt_params_AUA_Q[0]/self.opt_params_AUA[0])*proposed_params[1]
                proposed_params[2] = (self.opt_params_AUA_Q[1]/self.opt_params_AUA[1])*proposed_params[2]
                proposed_params[3] = (self.opt_params_AUA_Q[2]/self.opt_params_AUA[2])*proposed_params[3]
            
            
            self.w=np.random.random()
            
            #THIS IS IMPORTANT needs to be different depending on which direction
            
            proposed_params[4] = -(1/self.lamda)*np.log(self.w)
            #Propose a value of Q from an exponential distribution using the inverse CDF method (this is nice because it keeps the transition probability simple)

    
        elif proposed_model==0 and self.current_model==1:
            
            #AUA+Q ----> AUA
            
            
            if self.optimum_matching[0] =='True':
                #Optimum Matching
                proposed_params[1] = (self.opt_params_AUA[0]/self.opt_params_AUA_Q[0])*proposed_params[1]
                proposed_params[2] = (self.opt_params_AUA[1]/self.opt_params_AUA_Q[1])*proposed_params[2]
                proposed_params[3] = (self.opt_params_AUA[2]/self.opt_params_AUA_Q[2])*proposed_params[3]
            
            #w=params[4]/2
            
            #Still need to calculate what "w" (dummy variable) would be even though we don't use it (to satisfy detailed balance)
            self.w=np.exp(-self.lamda*proposed_params[4])
            
            
            
            
            proposed_params[4] = 0
            
        elif proposed_model==2 and self.current_model==0:
            
            #AUA--->UA
            
            proposed_params[1] = (self.opt_params_UA[0]/self.opt_params_AUA[0])*proposed_params[1]
            proposed_params[2] = (self.opt_params_UA[1]/self.opt_params_AUA[1])*proposed_params[2]
            proposed_params[3] = self.opt_params_UA[2]
            
            proposed_params[4] = 0
            self.w=1
            
            
        elif proposed_model==0 and self.current_model==2:
            #UA ----> AUA
        
            proposed_params[1] = (self.opt_params_AUA[0]/self.opt_params_UA[0])*proposed_params[1]
            proposed_params[2] = (self.opt_params_AUA[1]/self.opt_params_UA[1])*proposed_params[2]
            proposed_params[3] = (self.opt_params_AUA[2]/self.opt_params_UA[2])*proposed_params[3]    
            self.w=1
            proposed_params[4] = 0
        return proposed_params
        
    
    def parameter_proposal(self,prior,proposed_params,compound_2CLJ):
        
        rnorm = np.random.normal
        
        #Choose a random parameter to change
        if self.current_model == 0:
            modified_param=int(np.ceil(np.random.random()*(self.n_params-2)))
        elif self.current_model == 1:
            modified_param=int(np.ceil(np.random.random()*(self.n_params-1)))
        elif self.current_model == 2:
            modified_param=int(np.ceil(np.random.random()*(self.n_params-3)))
        
       
            
        proposed_params[modified_param] = rnorm(proposed_params[modified_param], self.prop_sd[modified_param])
        proposed_log_prob=self.calc_posterior(prior,compound_2CLJ,proposed_params,)
    
        return proposed_params, proposed_log_prob
    
    def Tune_RJMC(self):
        #print(np.sum(self.move_proposals))
        acceptance_rate = np.sum(self.move_acceptances)/np.sum(self.move_proposals)       
        #print(acceptance_rate)
        if acceptance_rate<0.2:
            self.prop_sd *= 0.9
            #print('Yes')
        elif acceptance_rate>0.5:
            self.prop_sd *= 1.1
            #print('No')         

    def Report(self,plotting=
               False):
        print('Proposed Moves:')
        print(self.move_proposals)
        print('==============================')
        print('Successful Moves:')
        print(self.move_acceptances)
        print('==============================')        
        prob_matrix=self.move_acceptances/self.move_proposals
        print('Ratio of successful moves')
        print(prob_matrix)
        print('==============================')
        transition_matrix=np.ones((3,3))
        transition_matrix[0,1]=self.move_acceptances[0,1]/np.sum(self.move_proposals,1)[0]
        transition_matrix[0,2]=self.move_acceptances[0,2]/np.sum(self.move_proposals,1)[0]
        transition_matrix[1,0]=self.move_acceptances[1,0]/np.sum(self.move_proposals,1)[1]
        transition_matrix[1,2]=self.move_acceptances[1,2]/np.sum(self.move_proposals,1)[1]
        transition_matrix[2,1]=self.move_acceptances[2,1]/np.sum(self.move_proposals,1)[2]
        transition_matrix[2,0]=self.move_acceptances[2,0]/np.sum(self.move_proposals,1)[2]
        transition_matrix[0,0]=1-transition_matrix[0,1]-transition_matrix[0,2]
        transition_matrix[1,1]=1-transition_matrix[1,0]-transition_matrix[1,2]
        transition_matrix[2,2]=1-transition_matrix[2,0]-transition_matrix[2,1]
        print('Transition Matrix:')
        print(transition_matrix)
        print('==============================')
        self.transition_matrix=transition_matrix
        
        
        self.trace_tuned = self.trace[self.tune_for:]
        self.logp_trace_tuned = self.logp_trace[self.tune_for:]
        self.percent_dev_trace_tuned = self.percent_dev_trace[self.tune_for:]
        
        
        self.lit_params,self.lit_devs=import_literature_values('two',self.compound)
        trace_equil=self.trace_tuned
        logp_trace_equil=self.logp_trace_tuned
        percent_dev_trace_equil=self.percent_dev_trace_tuned
        
           # Converts the array with number of model parameters into an array with the number of times there was 1 parameter or 2 parameters
        model_count = np.array([len(trace_equil[trace_equil[:,0]==0]),len(trace_equil[trace_equil[:,0]==1]),len(trace_equil[trace_equil[:,0]==2])])
        
        
        prob_0 = 1.*model_count[0]/(len(trace_equil))
        print('Percent that  model 0 is sampled: '+str(prob_0 * 100.)) #The percent that use 1 parameter model
        
        prob_1 = 1.*model_count[1]/(len(trace_equil))
        print('Percent that model 1 is sampled: '+str(prob_1 * 100.)) #The percent that use two center UA LJ
        
        prob_2 = 1.*model_count[2]/(len(trace_equil))
        print('Percent that model 2 is sampled: '+str(prob_2 * 100.)) #The percent that use two center UA LJ
        print('==============================')        
        self.prob=[prob_0,prob_1,prob_2]
        
        Exp_ratio = prob_0/prob_1
        
        print('Experimental sampling ratio: %2.3f' % Exp_ratio )
        print('==============================')        
        
        print('Detailed Balance')
        
        #These sets of numbers should be roughly equal to each other (If both models are sampled).  If not, big problem 
        
        print(prob_0*transition_matrix[0,1])
        print(prob_1*transition_matrix[1,0])
        
        print(prob_0*transition_matrix[0,2])
        print(prob_2*transition_matrix[2,0])
        
        print(prob_1*transition_matrix[1,2])
        print(prob_2*transition_matrix[2,1])
        print('==============================')        
        trace_model_0=[]
        trace_model_1=[]
        trace_model_2=[]
        '''
        log_trace_0=[]
        log_trace_1=[]
        log_trace_2=[]
        '''
        for i in range(np.size(trace_equil,0)):
            if trace_equil[i,0] == 0:
                trace_model_0.append(trace_equil[i])
                #log_trace_0.append(logp_trace[i])
            elif trace_equil[i,0] == 1:
                trace_model_1.append(trace_equil[i])
                #log_trace_1.append(logp_trace[i])
            elif trace_equil[i,0] == 2:
                trace_model_2.append(trace_equil[i])
                #log_trace_2.append(logp_trace[i])        
        
        
        self.trace_model_0=np.asarray(trace_model_0)
        self.trace_model_1=np.asarray(trace_model_1)
        self.trace_model_2=np.asarray(trace_model_2)
        
        self.BAR_trace=np.asarray(self.BAR_trace)
        
        BAR_vector_0 = []
        BAR_vector_1 = []
        BAR_vector_2 = []
        
        for i in range(len(self.BAR_trace)):
            if self.BAR_trace[i,0] == 0:
                BAR_vector_0.append(self.BAR_trace[i,1])
            elif self.BAR_trace[i,0] == 1:
                BAR_vector_1.append(self.BAR_trace[i,1])
            elif self.BAR_trace[i,0] == 2:
                BAR_vector_2.append(self.BAR_trace[i,1])   
        
        BAR_vector_0=np.asarray(BAR_vector_0)
        BAR_vector_1=np.asarray(BAR_vector_1)
        BAR_vector_2=np.asarray(BAR_vector_2)
        
        BAR_estimate=BAR(BAR_vector_0,BAR_vector_1)
        
        BF_BAR=np.exp(-BAR_estimate[0])
        BF_BAR_LB=np.exp(-(BAR_estimate[0]+BAR_estimate[1]))
        BF_BAR_UB=np.exp(-(BAR_estimate[0]-BAR_estimate[1]))
        print(BF_BAR)
        print(BF_BAR_LB,BF_BAR_UB)
        
        if plotting == True:
            
            
            
            create_param_triangle_plot_4D(self.trace_model_0,'trace_model_0',self.lit_params,self.properties,self.compound,self.steps)
            create_param_triangle_plot_4D(self.trace_model_1,'trace_model_1',self.lit_params,self.properties,self.compound,self.steps)
            create_param_triangle_plot_4D(self.trace_model_2,'trace_model_2',self.lit_params,self.properties,self.compound,self.steps)

            create_percent_dev_triangle_plot(percent_dev_trace_equil,'percent_dev_trace',self.lit_devs,self.prob,self.properties,self.compound,self.steps)
    
        
        return self.trace,self.logp_trace,self.percent_dev_trace,self.BAR_trace
    
    def refit_prior(self,prior_values):
        if prior_values['Q'][0] == 'exponential':
            new_prior=fit_exponential(self.trace_model_1[:,4])
            
            Q_prior=[new_prior[1]]
        return Q_prior
    
    def write_output(self,prior_dict,tag=None,save_traj=False):
        
        #Ask if output exists
        if os.path.isdir('output') == False:
            os.mkdir('output')
        if os.path.isdir('output/'+self.compound) == False:
            os.mkdir('output/'+self.compound)
        if os.path.isdir('output/'+self.compound+'/'+self.properties) == False:
            os.mkdir('output/'+self.compound+'/'+self.properties)
        
        path='output/'+self.compound+'/'+self.properties+'/'+self.compound+'_'+self.properties+'_'+str(self.steps)+'_'+tag+'_'+str(date.today())

        if os.path.isdir(path) == True:
            print('Directory Exists, overwriting')
            rmtree(path)
            os.mkdir(path)
        else:
            os.mkdir(path)
        
        os.mkdir(path+'/figures')
        
        print('Creating figures...')
        print('==============================')        
        plt.plot(self.logp_trace_tuned)
        plt.savefig(path+'/figures/logp_trace.png')
        plt.close()
        
        plt.plot(self.trace_tuned[:,0])
        plt.savefig(path+'/figures/model_trace.png')
        plt.close()
        
        create_param_triangle_plot_4D(self.trace_model_0,'triangle_plot_trace_model_0',self.lit_params,self.properties,self.compound,self.steps,file_loc=path+'/figures/')
        create_param_triangle_plot_4D(self.trace_model_1,'triangle_plot_trace_model_1',self.lit_params,self.properties,self.compound,self.steps,file_loc=path+'/figures/')
        create_param_triangle_plot_4D(self.trace_model_2,'triangle_plot_trace_model_2',self.lit_params,self.properties,self.compound,self.steps,file_loc=path+'/figures/')
        create_percent_dev_triangle_plot(self.percent_dev_trace_tuned,'triangle_plot_percent_dev_trace',self.lit_devs,self.properties,self.compound,self.steps,file_loc=path+'/figures/')
        plot_bar_chart(self.prob,self.properties,self.compound,self.steps,self.n_models,file_loc=path+'/figures/')


        print('Writing metadata...')
        print('==============================')        
        self.write_datapoints(path)
        
        self.write_metadata(path,prior_dict)
        
        self.write_simulation_results(path)
        
        if save_traj == True:
            print('Saving Trajectories')
            print('==============================')
            self.write_traces(path)
        
    def write_datapoints(self,path):
        
        datapoints={'Density Temperatures': self.thermo_data_rhoL[:,0],
                    'Density Values': self.thermo_data_rhoL[:,1],
                    'Density Measurement Uncertainties': self.thermo_data_rhoL[:,2],
                    'Saturation Pressure Temperatures': self.thermo_data_Pv[:,0],
                    'Saturation Pressure Values': self.thermo_data_Pv[:,1],
                    'Saturation Pressure Uncertainties': self.thermo_data_Pv[:,2],                    
                    'Surface Tension Temperatures': self.thermo_data_SurfTens[:,0],
                    'Surface Tension Values': self.thermo_data_SurfTens[:,1],
                    'Surface Tension Uncertainties': self.thermo_data_SurfTens[:,2],
                    'Literature Critical Temperature': self.Tc_lit[0]}
                    
        f=open(path+'/datapoints.txt',"w")
        f.write( str(datapoints) )
        f.close()
        
    def write_metadata(self,path,prior_dict):
        
        metadata=self.get_attributes()
        
        
        
        f=open(path+'/metadata.txt',"w")
        f.write(str(metadata))
        f.write(str(prior_dict))
        f.close()
    
    def write_simulation_results(self,path):
        results={'Proposed Moves': self.move_proposals,
                 'Tuning Frequency': self.tune_freq,
                 'Tuning Length': self.tune_for,
                 'Final Move SD': self.prop_sd,
                 'Accepted Moves': self.move_acceptances,
                 'Transition Matrix': self.transition_matrix,
                 'Model Probabilities':self.prob,
                 'Timestamp': str(datetime.today())}
        
        f=open(path+'/results.txt',"w")
        f.write( str(results) )
        f.close()
        
    def write_traces(self,path):
        if os.path.isdir(path+'/trace')==False:
            os.mkdir(path+'/trace')
        np.save(path+'/trace/trace.npy',self.trace_tuned)
        np.save(path+'/trace/logp_trace.npy',self.logp_trace_tuned)
        np.save(path+'/trace/percent_dev_trace_tuned.npy',self.percent_dev_trace_tuned)
        
        
        
        

class RJMC_Prior():
    """ Sets up a prior based on the user-specified prior types and parameters
    
    Attributes
    """

    def __init__(self,prior_dict):
        self.prior_dict=prior_dict
        
        self.dnorm = distributions.norm
        self.dgamma = distributions.gamma
        self.duni = distributions.uniform
        self.dlogit = distributions.logistic
        self.dexp = distributions.expon
    
    def epsilon_prior(self):
        eps_prior_type,eps_prior_vals = self.prior_dict['epsilon']
        
        if eps_prior_type == 'exponential':
            self.epsilon_prior_function = self.dexp
            self.epsilon_prior_values = [0,eps_prior_vals[0]]
        elif eps_prior_type == 'gamma':
            self.epsilon_prior_function = self.dgamma
            self.epsilon_prior_values = [eps_prior_vals[0],0,eps_prior_vals[1]]
            
    def sigma_prior(self):
        sig_prior_type,sig_prior_vals = self.prior_dict['sigma']
        
        if sig_prior_type == 'exponential':
            self.sigma_prior_function = self.dexp
            self.sigma_prior_values = [0,sig_prior_vals[0]]
        elif sig_prior_type == 'gamma':
            self.sigma_prior_function = self.dgamma
            self.sigma_prior_values = [sig_prior_vals[0],0,sig_prior_vals[1]]
            
    def L_prior(self):
        L_prior_type,L_prior_vals = self.prior_dict['L']
        
        if L_prior_type == 'exponential':
            self.L_prior_function = self.dexp
            self.L_prior_values = [0,L_prior_vals[0]]
        elif L_prior_type == 'gamma':
            self.L_prior_function = self.dgamma
            self.L_prior_values = [L_prior_vals[0],0,L_prior_vals[1]]
            
    def Q_prior(self):
        Q_prior_type,Q_prior_vals = self.prior_dict['Q']
        
        if Q_prior_type == 'exponential':
            self.Q_prior_function = self.dexp
            self.Q_prior_values = [0,Q_prior_vals[0]]
        elif Q_prior_type == 'gamma':
            self.Q_prior_function = self.dgamma
            self.Q_prior_values = [Q_prior_vals[0],0,Q_prior_vals[1]]
                   
    
            
            
              
             
        
    
        
        
def main():
    
    parser = argparse.ArgumentParser(description='Process input parameters for RJMC 2CLJQ')
    
    parser.add_argument('--compound','-c',
                        type=str,
                        help='Compound to simulate parameters for',
                        required=True)

    parser.add_argument('--trange','-t',
                        type=list,
                        help='Temperature range for data to include',
                        required=False)

    parser.add_argument('--steps','-s',
                        type=int,
                        help='Number of MCMC steps',
                        required=True)      
    
    parser.add_argument('--properties','-p',
                        type=str,
                        help='Properties to include in computation',
                        required=True)      

    parser.add_argument('--priors','-r',
                        type=dict,
                        help='Values and types of prior distribution',
                        required=False)        
    
    parser.add_argument('--optimum_matching','-o',
                        type=list,
                        help='Whether to use optimum matching in transitions',
                        required=False)        

    
    parser.add_argument('--number_data_points','-d',
                        type=int,
                        help='Number of data points to include',
                        required=False)        
    
    parser.add_argument('--swap_freq','-f',
                        type=float,
                        help='Frequency of model jump proposal',
                        required=False)        
    
    parser.add_argument('--biasing_factor','-b',
                        type=list,
                        help='Biasing factors for each model',
                        required=False)        
    parser.add_argument('--label','-l',
                        type=str,
                        help='label for files',
                        required=False)        
    parser.add_argument('--save_traj','-j',
                        type=bool,
                        help='Whether to save trajectory files',
                        required=False)        
   
   
    T_range=[0.55,0.95]
    n_points=10
    swap_freq=0.1
    biasing_factor=[0,0,0]
    optimum_matching=['True','True']
    tag=''
    save_traj=False
    
    
    prior_values ={
        'epsilon': ['exponential',[400]],
        'sigma': ['exponential',[5]],
        'L': ['exponential',[3]],
        'Q': ['exponential',[1]]}
    
    args = parser.parse_args()
    print(args.compound)
    
    compound=args.compound
    #T_range=args.trange
    steps=args.steps
    properties=args.properties

    if args.trange is not None:
        T_range=args.trange
    if args.number_data_points is not None:
        n_points=args.number_data_points
    if args.swap_freq is not None:
        swap_freq=args.swap_freq
    if args.biasing_factor is not None:
        biasing_factor=args.biasing_factor
    if args.optimum_matching is not None:
        optimum_matching=args.optimum_matching
    if args.priors is not None:
        prior_values=args.priors
    if args.label is not None:
        tag=args.label
    if args.save_traj is not None:
        save_traj=args.save_traj
    
    
    prior = RJMC_Prior(prior_values)
    prior.epsilon_prior()
    prior.sigma_prior()
    prior.L_prior()
    prior.Q_prior()     

    
    
    
    rjmc_simulator = RJMC_Simulation(compound,T_range,properties,n_points,steps,swap_freq,biasing_factor,optimum_matching)

    rjmc_simulator.prepare_data()
    
    print('Simulation Attributes:',rjmc_simulator.get_attributes())

    compound_2CLJ = LennardJones_2C(rjmc_simulator.M_w) 

    rjmc_simulator.gen_Tmatrix(prior,compound_2CLJ)    
    #print(rjmc_simulator.opt_params_AUA)
    rjmc_simulator.set_initial_state(prior,compound_2CLJ)

    rjmc_simulator.RJMC_Outerloop(prior,compound_2CLJ)
    trace,logp_trace,percent_dev_trace=rjmc_simulator.Report()
    rjmc_simulator.write_output(prior_values,tag=tag,save_traj=save_traj)
    print('Finished!')

  

    
if __name__ == '__main__':
    main()