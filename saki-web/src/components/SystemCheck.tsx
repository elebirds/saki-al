import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Spin } from 'antd';
import { api } from '../services/api';

// Component to handle system initialization check
const SystemCheck: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [loading, setLoading] = useState(true);
  const [_initialized, setInitialized] = useState(true);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (location.pathname === '/network-error') {
      setLoading(false);
      return;
    }

    const checkStatus = async () => {
      try {
        const status = await api.getSystemStatus();
        setInitialized(status.initialized);
        
        // If not initialized and not already on setup page, go to setup
        if (!status.initialized && location.pathname !== '/setup') {
          navigate('/setup');
        }
        // If initialized and trying to access setup, go to login
        if (status.initialized && location.pathname === '/setup') {
          navigate('/login');
        }
      } catch (error) {
        console.error("Failed to check system status", error);
      } finally {
        setLoading(false);
      }
    };
    checkStatus();
  }, [navigate, location.pathname]);

  if (loading) {
    return <div style={{ height: '100vh', display: 'flex', justifyContent: 'center', alignItems: 'center' }}><Spin size="large" /></div>;
  }

  return <>{children}</>;
};

export default SystemCheck;
