import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import DatasetList from './pages/dataset/DatasetList';
import DatasetDetail from './pages/dataset/DatasetDetail';
import WorkspaceRouter from './pages/annotation/WorkspaceRouter';
import UserManagement from './pages/user/UserManagement';
import Login from './pages/user/Login';
import Register from './pages/user/Register';
import ChangePassword from './pages/user/ChangePassword';
import Setup from './pages/base/Setup';
import NetworkError from './pages/base/NetworkError';
import SystemCheck from './components/SystemCheck';
import ProtectedLayout from './components/ProtectedLayout';

const App: React.FC = () => {
  const { t } = useTranslation();
  return (
    <Router>
      <SystemCheck>
        <Routes>
          <Route path="/network-error" element={<NetworkError />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/change-password" element={<ChangePassword />} />
          
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<DatasetList />} />
            <Route path="/datasets/:id" element={<DatasetDetail />} />
            <Route path="/workspace/:datasetId" element={<WorkspaceRouter />} />
            <Route path="/users" element={<UserManagement />} />
            <Route path="/about" element={<div><h2>{t('app.about')}</h2><p>Saki is a visual active learning framework.</p></div>} />
          </Route>
        </Routes>
      </SystemCheck>
    </Router>
  );
};

export default App;
