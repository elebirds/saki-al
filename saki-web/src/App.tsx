import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ProjectList from './pages/ProjectList';
import ProjectDetail from './pages/ProjectDetail';
import AnnotationWorkspace from './pages/AnnotationWorkspace';
import UserManagement from './pages/UserManagement';
import Login from './pages/Login';
import Register from './pages/Register';
import Setup from './pages/Setup';
import NetworkError from './pages/NetworkError';
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
          
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<ProjectList />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/workspace/:projectId" element={<AnnotationWorkspace />} />
            <Route path="/users" element={<UserManagement />} />
            <Route path="/about" element={<div><h2>{t('app.about')}</h2><p>Saki is a visual active learning framework.</p></div>} />
          </Route>
        </Routes>
      </SystemCheck>
    </Router>
  );
};

export default App;
