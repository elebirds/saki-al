import React, {Suspense, lazy} from 'react';
import {BrowserRouter as Router, Navigate, Route, Routes} from 'react-router-dom';
import {useInitPermissions, useInitSystemCapabilities} from './hooks';

const DatasetList = lazy(() => import('./pages/dataset/DatasetList'));
const DatasetDetail = lazy(() => import('./pages/dataset/DatasetDetail'));
const ProjectOverview = lazy(() => import('./pages/project/ProjectOverview'));
const ProjectLayout = lazy(() => import('./pages/project/ProjectLayout'));
const ProjectList = lazy(() => import('./pages/project/ProjectList'));
const ProjectBranches = lazy(() => import('./pages/project/ProjectBranches'));
const ProjectCommits = lazy(() => import('./pages/project/ProjectCommits'));
const ProjectCommitDetail = lazy(() => import('./pages/project/ProjectCommitDetail'));
const ProjectSamplesAnnotations = lazy(() => import('./pages/project/ProjectSamplesAnnotations'));
const ProjectInsights = lazy(() => import('./pages/project/ProjectInsights'));
const ProjectModels = lazy(() => import('./pages/project/ProjectModels'));
const ProjectSettings = lazy(() => import('./pages/project/ProjectSettings'));
const ProjectWorkspace = lazy(() => import('./pages/project/ProjectWorkspace'));
const ProjectExportWorkspace = lazy(() => import('./pages/export/ProjectExportWorkspace'));
const DatasetImportWorkspace = lazy(() => import('./pages/import/DatasetImportWorkspace'));
const ProjectImportWorkspace = lazy(() => import('./pages/import/ProjectImportWorkspace'));
const ProjectLoopOverview = lazy(() => import('./pages/project/loops/ProjectLoopOverview'));
const ProjectLoopCreate = lazy(() => import('./pages/project/loops/ProjectLoopCreate'));
const ProjectLoopDetail = lazy(() => import('./pages/project/loops/ProjectLoopDetail'));
const ProjectLoopConfig = lazy(() => import('./pages/project/loops/ProjectLoopConfig'));
const ProjectLoopRoundDetail = lazy(() => import('./pages/project/loops/ProjectLoopRoundDetail'));
const ProjectPredictionTasks = lazy(() => import('./pages/project/loops/ProjectPredictionTasks'));
const ProjectPredictionTaskDetail = lazy(() => import('./pages/project/loops/ProjectPredictionTaskDetail'));
const UserManagement = lazy(() => import('./pages/user/UserManagement'));
const RoleManagement = lazy(() => import('./pages/user/RoleManagement'));
const UserProfile = lazy(() => import('./pages/user/UserProfile'));
const SystemSettings = lazy(() => import('./pages/system/SystemSettings'));
const About = lazy(() => import('./pages/about/About'));
const Login = lazy(() => import('./pages/user/Login'));
const Register = lazy(() => import('./pages/user/Register'));
const ChangePassword = lazy(() => import('./pages/user/ChangePassword'));
const Setup = lazy(() => import('./pages/base/Setup'));
const NetworkError = lazy(() => import('./pages/base/NetworkError'));
const RuntimeExecutors = lazy(() => import('./pages/runtime/RuntimeExecutors'));
const RuntimeReleases = lazy(() => import('./pages/runtime/RuntimeReleases'));
const SystemCheck = lazy(() => import('./components/SystemCheck'));
const ProtectedLayout = lazy(() => import('./components/ProtectedLayout'));

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

const RouteLoadingFallback: React.FC = () => (
    <div className="flex min-h-screen items-center justify-center text-sm text-gray-500">
        Loading...
    </div>
);

const App: React.FC = () => {
    return (
        <Router>
            <Suspense fallback={<RouteLoadingFallback/>}>
                <SystemCheck>
                    <PermissionInitializer>
                        <SystemCapabilitiesInitializer>
                            <Routes>
                                <Route path="/network-error" element={<NetworkError/>}/>
                                <Route path="/setup" element={<Setup/>}/>
                                <Route path="/login" element={<Login/>}/>
                                <Route path="/register" element={<Register/>}/>
                                <Route path="/change-password" element={<ChangePassword forceMode/>}/>

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
                                        <Route path="loops/create" element={<ProjectLoopCreate/>}/>
                                        <Route path="loops/:loopId" element={<ProjectLoopDetail/>}/>
                                        <Route path="loops/:loopId/config" element={<ProjectLoopConfig/>}/>
                                        <Route path="loops/:loopId/rounds/:roundId" element={<ProjectLoopRoundDetail/>}/>
                                        <Route path="prediction-tasks" element={<ProjectPredictionTasks/>}/>
                                        <Route path="prediction-tasks/:predictionId" element={<ProjectPredictionTaskDetail/>}/>
                                        <Route path="models" element={<ProjectModels/>}/>
                                        <Route path="insights" element={<ProjectInsights/>}/>
                                        <Route path="settings" element={<ProjectSettings/>}/>
                                        <Route path="workspace" element={<ProjectWorkspace/>}/>
                                        <Route path="workspace/:datasetId" element={<ProjectWorkspace/>}/>
                                    </Route>
                                    <Route path="/runtime/executors" element={<RuntimeExecutors/>}/>
                                    <Route path="/runtime/releases" element={<RuntimeReleases/>}/>
                                    <Route
                                        path="/projects/:projectId/members"
                                        element={<Navigate to="../settings?section=members" replace/>}
                                    />

                                    <Route path="/users" element={<UserManagement/>}/>
                                    <Route path="/roles" element={<RoleManagement/>}/>
                                    <Route path="/system/settings" element={<SystemSettings/>}/>
                                    <Route path="/profile" element={<UserProfile/>}/>
                                    <Route path="/profile/change-password" element={<ChangePassword/>}/>
                                    <Route path="/about" element={<About/>}/>
                                </Route>
                            </Routes>
                        </SystemCapabilitiesInitializer>
                    </PermissionInitializer>
                </SystemCheck>
            </Suspense>
        </Router>
    );
};

export default App;
