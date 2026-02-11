import React from 'react'
import {Outlet} from 'react-router-dom'

const ProjectLayout: React.FC = () => {
    return (
        <div className="flex h-full flex-col">
            <div className="flex-1 min-h-0 overflow-x-hidden overflow-y-auto">
                <Outlet/>
            </div>
        </div>
    )
}

export default ProjectLayout
