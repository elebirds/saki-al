import React from 'react';
import {BrowserRouter as Router, Navigate, Route, Routes} from 'react-router-dom';
import DatasetList from './pages/dataset/DatasetList';
import DatasetDetail from './pages/dataset/DatasetDetail';
import ProjectOverview from './pages/project/ProjectOverview';
import ProjectLayout from './pages/project/ProjectLayout';
import ProjectList from './pages/project/ProjectList';
import ProjectBranches from './pages/project/ProjectBranches';
import ProjectCommits from './pages/project/ProjectCommits';
import ProjectCommitDetail from './pages/project/ProjectCommitDetail';
import ProjectSamplesAnnotations from './pages/project/ProjectSamplesAnnotations';
import ProjectInsights from './pages/project/ProjectInsights';
import ProjectSettings from './pages/project/ProjectSettings';
import ProjectWorkspace from './pages/project/ProjectWorkspace';
import ProjectExportWorkspace from './pages/export/ProjectExportWorkspace';
import DatasetImportWorkspace from './pages/import/DatasetImportWorkspace';
import ProjectImportWorkspace from './pages/import/ProjectImportWorkspace';
import ProjectLoopOverview from './pages/project/loops/ProjectLoopOverview';
import ProjectLoopDetail from './pages/project/loops/ProjectLoopDetail';
import ProjectLoopConfig from './pages/project/loops/ProjectLoopConfig';
import ProjectLoopRoundDetail from './pages/project/loops/ProjectLoopRoundDetail';
import UserManagement from './pages/user/UserManagement';
import RoleManagement from './pages/user/RoleManagement';
import UserProfile from './pages/user/UserProfile';
import SystemSettings from './pages/system/SystemSettings';
import About from './pages/about/About';
import Login from './pages/user/Login';
import Register from './pages/user/Register';
import ChangePassword from './pages/user/ChangePassword';
import Setup from './pages/base/Setup';
import NetworkError from './pages/base/NetworkError';
import RuntimeExecutors from './pages/runtime/RuntimeExecutors';
import SystemCheck from './components/SystemCheck';
import ProtectedLayout from './components/ProtectedLayout';
import {useInitPermissions, useInitSystemCapabilities} from './hooks';

// Permission initialization wrapper
const PermissionInitializer: React.FC<{ children: React.ReactNode }> = ({children}) => {
    useInitPermissions();
    return <>{children}</>;
};

// System capabilities initialization wrapper
const SystemCapabilitiesInitializer: React.FC<{ children: React.ReactNode }> = ({children}) => {
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
                            <Route path="/network-error" element={<NetworkError/>}/>
                            <Route path="/setup" element={<Setup/>}/>
                            <Route path="/login" element={<Login/>}/>
                            <Route path="/register" element={<Register/>}/>
                            <Route path="/change-password" element={<ChangePassword/>}/>

                            <Route element={<ProtectedLayout/>}>
                                <Route path="/" element={<DatasetList/>}/>
                                <Route path="/datasets" element={<DatasetList/>}/>
                                <Route path="/datasets/:id" element={<DatasetDetail/>}/>
                                <Route path="/datasets/:id/import" element={<DatasetImportWorkspace/>}/>
                                <Route path="/projects" element={<ProjectList/>}/>
                                <Route path="/projects/:projectId" element={<ProjectLayout/>}>
                                    <Route index element={<ProjectOverview/>}/>
                                    <Route path="branches" element={<ProjectBranches/>}/>
                                    <Route path="commits" element={<ProjectCommits/>}/>
                                    <Route path="commits/:commitId" element={<ProjectCommitDetail/>}/>
                                    <Route path="samples" element={<ProjectSamplesAnnotations/>}/>
                                    <Route path="import" element={<ProjectImportWorkspace/>}/>
                                    <Route path="export" element={<ProjectExportWorkspace/>}/>
                                    <Route path="loops" element={<ProjectLoopOverview/>}/>
                                    <Route path="loops/:loopId" element={<ProjectLoopDetail/>}/>
                                    <Route path="loops/:loopId/config" element={<ProjectLoopConfig/>}/>
                                    <Route path="loops/:loopId/rounds/:roundId" element={<ProjectLoopRoundDetail/>}/>
                                    <Route path="insights" element={<ProjectInsights/>}/>
                                    <Route path="settings" element={<ProjectSettings/>}/>
                                    <Route path="workspace" element={<ProjectWorkspace/>}/>
                                    <Route path="workspace/:datasetId" element={<ProjectWorkspace/>}/>
                                </Route>
                                <Route path="/runtime/executors" element={<RuntimeExecutors/>}/>
                                <Route
                                    path="/projects/:projectId/members"
                                    element={<Navigate to="../settings?section=members" replace/>}
                                />

                                <Route path="/users" element={<UserManagement/>}/>
                                <Route path="/roles" element={<RoleManagement/>}/>
                                <Route path="/system/settings" element={<SystemSettings/>}/>
                                <Route path="/profile" element={<UserProfile/>}/>
                                <Route path="/about" element={<About/>}/>
                            </Route>
                        </Routes>
                    </SystemCapabilitiesInitializer>
                </PermissionInitializer>
            </SystemCheck>
        </Router>
    );
};

export default App;
