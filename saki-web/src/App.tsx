import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import DatasetList from './pages/dataset/DatasetList';
import DatasetDetail from './pages/dataset/DatasetDetail';
import ProjectOverview from './pages/project/ProjectOverview';
import WorkspaceRouter from './pages/annotation/WorkspaceRouter';
import UserManagement from './pages/user/UserManagement';
import RoleManagement from './pages/user/RoleManagement';
import UserProfile from './pages/user/UserProfile';
import About from './pages/about/About';
import Login from './pages/user/Login';
import Register from './pages/user/Register';
import ChangePassword from './pages/user/ChangePassword';
import Setup from './pages/base/Setup';
import NetworkError from './pages/base/NetworkError';
import SystemCheck from './components/SystemCheck';
import ProtectedLayout from './components/ProtectedLayout';
import { useInitPermissions, useInitSystemCapabilities } from './hooks';

// Permission initialization wrapper
const PermissionInitializer: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  useInitPermissions();
  return <>{children}</>;
};

// System capabilities initialization wrapper
const SystemCapabilitiesInitializer: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  useInitSystemCapabilities();
  return <>{children}</>;
};

const App: React.FC = () => {
  return (
    <Router>
      <SystemCheck>
        <PermissionInitializer>
          <SystemCapabilitiesInitializer>
            <Routes>
              <Route path="/network-error" element={<NetworkError />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/change-password" element={<ChangePassword />} />
              
              <Route element={<ProtectedLayout />}>
              <Route path="/" element={<DatasetList />} />
              <Route path="/datasets" element={<DatasetList />} />
              <Route path="/datasets/:id" element={<DatasetDetail />} />
              <Route path="/projects" element={<ProjectOverview />} />
                
                {/* Workspace still points to legacy dataset logic inside? Maybe need check */}
                <Route path="/workspace/:datasetId" element={<WorkspaceRouter />} />
                <Route path="/users" element={<UserManagement />} />
                <Route path="/roles" element={<RoleManagement />} />
                <Route path="/profile" element={<UserProfile />} />
                <Route path="/about" element={<About />} />
              </Route>
            </Routes>
          </SystemCapabilitiesInitializer>
        </PermissionInitializer>
      </SystemCheck>
    </Router>
  );
};

export default App;
