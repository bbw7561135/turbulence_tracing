import numpy as np
from scipy.integrate import odeint,solve_ivp
from scipy.interpolate import RegularGridInterpolator
from time import time

c = 299792458 # honestly, this could be 3e8 *shrugs*


class ElectronCube:
    """A class to hold and generate electron density cubes
    """
    
    def __init__(self, x, y, z, extent):
        """
        Example:
            N_V = 100
            M_V = 2*N_V+1
            ne_extent = 5.0e-3
            ne_x = np.linspace(-ne_extent,ne_extent,M_V)
            ne_y = np.linspace(-ne_extent,ne_extent,M_V)
            ne_z = np.linspace(-ne_extent,ne_extent,M_V)

        Args:
            x (float array): x coordinates, m
            y (float array): y coordinates, m
            z (float array): z coordinates, m
            extent (float): physical size, m
        """
        self.z,self.y,self.x = z, y, x
        self.XX, self.YY, self.ZZ = np.meshgrid(x,y,z, indexing='ij')
        self.extent = extent
        
        self.XX_ravel = self.XX.ravel()
        self.YY_ravel = self.YY.ravel()
        self.ZZ_ravel = self.ZZ.ravel()
        
    def test_null(self):
        """
        Null test, an empty cube
        """
        self.ne = np.zeros_like(self.XX)
        
    def test_slab(self, s=1, n_e0=2e23):
        """A slab with a linear gradient in x:
        n_e =  n_e0 * (1 + s*x/extent)

        Will cause a ray deflection in x

        Args:
            s (int, optional): scale factor. Defaults to 1.
            n_e0 ([type], optional): mean density. Defaults to 2e23 m^-3.
        """
        self.ne = n_e0*(1.0+s*self.XX/self.extent)
        
    def test_linear_cos(self,s1=0.1,s2=0.1,n_e0=2e23,Ly=1):
        """Linearly growing sinusoidal perturbation

        Args:
            s1 (float, optional): scale of linear growth. Defaults to 0.1.
            s2 (float, optional): amplitude of sinusoidal perturbation. Defaults to 0.1.
            n_e0 ([type], optional): mean electron density. Defaults to 2e23 m^-3.
            Ly (int, optional): spatial scale of sinusoidal perturbation. Defaults to 1.
        """
        self.ne = n_e0*(1.0+s1*self.XX/self.extent)*(1+s2*np.cos(2*np.pi*self.YY/Ly))
        
    def test_exponential_cos(self,n_e0=1e24,Ly=1e-3, s=2e-3):
        """Exponentially growing sinusoidal perturbation

        Args:
            n_e0 ([type], optional): mean electron density. Defaults to 2e23 m^-3.
            Ly (int, optional): spatial scale of sinusoidal perturbation. Defaults to 1e-3 m.
            s ([type], optional): scale of exponential growth. Defaults to 2e-3 m.
        """
        self.ne = n_e0*10**(self.XX/s)*(1+np.cos(2*np.pi*self.YY/Ly))
        
    def external_ne(self, ne):
        """Load externally generated grid

        Args:
            ne ([type]): MxMxM grid of density in m^-3
        """
        self.ne = ne
        
    def calc_dndr(self, lwl=1053e-9):
        """Generate interpolators for derivatives.

        Args:
            lwl (float, optional): laser wavelength. Defaults to 1053e-9 m.
        """

        omega = 2*np.pi*(c/lwl)
        nc = 3.14207787e-4*omega**2

        self.ne_nc = self.ne/nc #normalise to critical density
        
        #More compact notation is possible here, but we are explicit
        self.dndx = -0.5*c**2*np.gradient(self.ne_nc,self.x,axis=0)
        self.dndy = -0.5*c**2*np.gradient(self.ne_nc,self.y,axis=1)
        self.dndz = -0.5*c**2*np.gradient(self.ne_nc,self.z,axis=2)
        
        self.dndx_interp = RegularGridInterpolator((self.x, self.y, self.z), self.dndx, bounds_error = False, fill_value = 0.0)
        self.dndy_interp = RegularGridInterpolator((self.x, self.y, self.z), self.dndy, bounds_error = False, fill_value = 0.0)
        self.dndz_interp = RegularGridInterpolator((self.x, self.y, self.z), self.dndz, bounds_error = False, fill_value = 0.0)
        
    def plot_midline_gradients(self,ax,probing_direction):
        """I actually don't know what this does. Presumably plots the gradients half way through the box? Cool.

        Args:
            ax ([type]): [description]
            probing_direction ([type]): [description]
        """
        N_V = self.x.shape[0]//2
        if(probing_direction == 'x'):
            ax.plot(self.y,self.dndx[:,N_V,N_V])
            ax.plot(self.y,self.dndy[:,N_V,N_V])
            ax.plot(self.y,self.dndz[:,N_V,N_V])
        elif(probing_direction == 'y'):
            ax.plot(self.y,self.dndx[N_V,:,N_V])
            ax.plot(self.y,self.dndy[N_V,:,N_V])
            ax.plot(self.y,self.dndz[N_V,:,N_V])
        elif(probing_direction == 'z'):
            ax.plot(self.y,self.dndx[N_V,N_V,:])
            ax.plot(self.y,self.dndy[N_V,N_V,:])
            ax.plot(self.y,self.dndz[N_V,N_V,:])
        else: # Default to y
            ax.plot(self.y,self.dndx[N_V,:,N_V])
            ax.plot(self.y,self.dndy[N_V,:,N_V])
            ax.plot(self.y,self.dndz[N_V,:,N_V])
    
    def dndr(self,x):
        """returns the gradient at the locations x

        Args:
            x (3xN float): N [x,y,z] locations

        Returns:
            3 x N float: N [dx,dy,dz] electron density gradients
        """
        grad = np.zeros_like(x)
        grad[0,:] = self.dndx_interp(x.T)
        grad[1,:] = self.dndy_interp(x.T)
        grad[2,:] = self.dndz_interp(x.T)
        return grad

    def solve(self, s0):
        # Need to make sure all rays have left volume
        # Conservative estimate of diagonal across volume
        # Then can backproject to surface of volume

        t  = np.linspace(0.0,np.sqrt(8.0)*self.extent/c,10)

        s0 = s0.flatten() #odeint insists

        start = time()
        dsdt_ODE = lambda t, y: dsdt(t, y, self)
        sol = solve_ivp(dsdt_ODE, [0,t[-1]], s0, t_eval=t)
        finish = time()
        print("Ray trace completed in:\t",finish-start,"s")

        Np = s0.size//6
        self.sf = sol.y[:,-1].reshape(6,Np)
        self.rf = find_angles(self.sf, self.extent)
    
# ODEs of photon paths
def dsdt(t, s, ElectronCube):
    Np = s.size//6
    s = s.reshape(6,Np)
    r = np.zeros_like(s)
    v = s[3:,:]
    x = s[:3,:]
    
    r[3:,:] = ElectronCube.dndr(x)
    r[:3,:] = v
    return r.flatten()

def init_beam(Np, beam_size, divergence, ne_extent, probing_direction = 'z'):
    """[summary]

    Args:
        Np (int): Number of photons
        beam_size (float): beam radius, m
        divergence (float): beam divergence, radians
        ne_extent (float): size of electron density cube, m. Used to back propagate the rays to the start
        probing_direction (str): direction of probing. I suggest 'z', the best tested

    Returns:
        s0, 6 x N float: N photons with (x, y, z, vx, vy, vz) in m, m/s.
    """
    s0 = np.zeros((6,Np))
    # position, uniformly within a circle
    t  = 2*np.pi*np.random.rand(Np) #polar angle of position
    u  = np.random.rand(Np)+np.random.rand(Np) # radial coordinate of position
    u[u > 1] = 2-u[u > 1]
    # angle
    ϕ = np.pi*np.random.rand(Np) #azimuthal angle of velocity
    χ = divergence*np.random.randn(Np) #polar angle of velocity

    if(probing_direction == 'x'):
        # Initial velocity
        s0[3,:] = c * np.cos(χ)
        s0[4,:] = c * np.sin(χ) * np.cos(ϕ)
        s0[5,:] = c * np.sin(χ) * np.sin(ϕ)
        # Initial position
        s0[0,:] = -ne_extent
        s0[1,:] = beam_size*u*np.cos(t)
        s0[2,:] = beam_size*u*np.sin(t)
    elif(probing_direction == 'y'):
        # Initial velocity
        s0[4,:] = c * np.cos(χ)
        s0[3,:] = c * np.sin(χ) * np.cos(ϕ)
        s0[5,:] = c * np.sin(χ) * np.sin(ϕ)
        # Initial position
        s0[0,:] = beam_size*u*np.cos(t)
        s0[1,:] = -ne_extent
        s0[2,:] = beam_size*u*np.sin(t)
    elif(probing_direction == 'z'):
        # Initial velocity
        s0[3,:] = c * np.sin(χ) * np.cos(ϕ)
        s0[4,:] = c * np.sin(χ) * np.sin(ϕ)
        s0[5,:] = c * np.cos(χ)
        # Initial position
        s0[0,:] = beam_size*u*np.cos(t)
        s0[1,:] = beam_size*u*np.sin(t)
        s0[2,:] = -ne_extent
    else: # Default to y
        print("Default to y")
        # Initial velocity
        s0[4,:] = c * np.cos(χ)
        s0[3,:] = c * np.sin(χ) * np.cos(ϕ)
        s0[5,:] = c * np.sin(χ) * np.sin(ϕ)        
        # Initial position
        s0[0,:] = beam_size*u*np.cos(t)
        s0[1,:] = -ne_extent
        s0[2,:] = beam_size*u*np.sin(t)
    return s0

# Need to backproject to ne volume, then find angles
def find_angles(ode_sol, ne_extent, probing_direction = 'z'):
    """Takes the output from the 6D solver and returns 4D rays for ray-transfer matrix techniques.
    Effectively finds how far the ray is from the end of the volume, returns it to the end of the volume.

    Args:
        ode_sol (6xN float): N rays in (x,y,z,vx,vy,vz) format, m and m/s
        ne_extent (float): edge length of cube, m
        probing_direction (str): x, y or z.

    Returns:
        [type]: [description]
    """
    Np = ode_sol.shape[1] # number of photons
    ray_p = np.zeros((4,Np))

    x, y, z, vx, vy, vz = ode_sol[0], ode_sol[1], ode_sol[2], ode_sol[3], ode_sol[4], ode_sol[5]

    # YZ plane
    if(probing_direction == 'x'):
        t_bp = (x-ne_extent)/vx
        # Positions on plane
        ray_p[0] = y-vy*t_bp
        ray_p[2] = z-vz*t_bp
        # Angles to plane
        ray_p[1] = np.arctan(vy/vx)
        ray_p[3] = np.arctan(vz/vx)
    # XZ plane
    elif(probing_direction == 'y'):
        t_bp = (y-ne_extent)/vy
        # Positions on plane
        ray_p[0] = x-vx*t_bp
        ray_p[2] = z-vz*t_bp
        # Angles to plane
        ray_p[1] = np.arctan(vx/vy)
        ray_p[3] = np.arctan(vz/vy)
    # XY plane
    elif(probing_direction == 'z'):
        t_bp = (z-ne_extent)/vz
        # Positions on plane
        ray_p[0] = x-vx*t_bp
        ray_p[2] = y-vy*t_bp
        # Angles to plane
        ray_p[1] = np.arctan(vx/vz)
        ray_p[3] = np.arctan(vy/vz)
    return ray_p