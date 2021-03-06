import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Container,
  Grid,
  IconButton,
  Paper,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@material-ui/core';

import { makeStyles } from '@material-ui/core/styles';

import {
  Edit as EditIcon,
  Settings as SettingsIcon,
} from '@material-ui/icons';

import Link from 'next/link';
import MangaAliases from './MangaAliases';
import MangaInfo from './MangaInfo';

import MangaSourceList from './MangaSourceList';
import { followUnfollow } from '../utils/utilities';
import ChapterList from './ChapterList';
import { useUser } from '../utils/useUser';
import ReleaseHeatmap from './ReleaseHeatmap';
import { TabPanelCustom } from './utils/TabPanelCustom';


const useStyles = makeStyles((theme) => ({
  title: {
    width: '75%',
    textAlign: 'left',
    paddingBottom: '10px',
    [theme.breakpoints.down('sm')]: {
      width: '100%',
    },
  },
  titleBar: {
    display: 'flex',
    justifyContent: 'space-between',
  },
  titleBarButtonsContainer: {
    display: 'flex',
  },
  thumbnail: {
    maxWidth: '250px',
    maxHeight: '355px',
    [theme.breakpoints.down('sm')]: {
      maxWidth: '200px',
    },
    [theme.breakpoints.down('xs')]: {
      maxWidth: '250px',
    },
  },
  details: {
    display: 'flex',
    flexFlow: 'row',
    [theme.breakpoints.down('xs')]: {
      flexFlow: 'wrap',
      justifyContent: 'center',
    },
  },
  detailText: {
    marginLeft: '5px',
    [theme.breakpoints.down('sm')]: {
      marginLeft: '3px',
    },
  },
  infoTable: {
    marginLeft: '30px',
    marginTop: '3px',
    [theme.breakpoints.down('sm')]: {
      marginLeft: '20px',
    },
    [theme.breakpoints.down('xs')]: {
      marginLeft: '10px',
    },
  },
  sourceList: {
    marginLeft: '35px',
    [theme.breakpoints.down('sm')]: {
      marginLeft: '23px',
    },
    [theme.breakpoints.down('xs')]: {
      marginLeft: '13px',
    },
  },
  followButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
  },
  paper: {
    padding: '1em',
    minWidth: '440px',
  },
  infoGrid: {
    marginLeft: theme.spacing(4),
    width: 'fit-content',
    [theme.breakpoints.down('xs')]: {
      marginLeft: '0px',
    },
  },
  rootGrid: {
    [theme.breakpoints.down('xs')]: {
      justifyContent: 'center',
    },
  },
}));


function Manga(props) {
  const {
    mangaData,
    userFollows = [],
  } = props;

  const [releaseData, setReleaseData] = useState([]);
  const [activeTab, setActiveTab] = useState(0);
  const changeTab = useCallback((e, newVal) => setActiveTab(newVal), []);

  useEffect(() => {
    fetch(`/api/chapter/releases/${mangaData.manga_id}`)
      .then(res => res.json())
      .then(js => {
        setReleaseData(js);
      });
  }, [mangaData.manga_id]);

  const { isAuthenticated, user } = useUser();

  const classes = useStyles();
  const [editing, setEditing] = useState(false);
  const startEditing = useCallback(() => setEditing(!editing), [editing]);

  const serviceUrlFormats = useMemo(() => {
    const serviceMap = {};
    mangaData.services.forEach(service => { serviceMap[service.service_id] = service.url_format });
    return serviceMap;
  }, [mangaData.services]);

  const mangaChapters = React.useMemo(() => {
    if (!mangaData.chapters) return [];
    const serviceMap = {};
    mangaData.services.forEach(service => { serviceMap[service.service_id] = service.url_format });
    return mangaData.chapters.map(chapter => {
      const newChapter = { ...chapter };
      newChapter.release_date = new Date(chapter.release_date);
      newChapter.url = serviceMap[chapter.service_id].replace('{}', chapter.chapter_url);
      return newChapter;
    });
  }, [mangaData.chapters, mangaData.services]);

  return (
    <Container maxWidth='lg' disableGutters>
      <Paper className={classes.paper}>
        <div className={classes.titleBar}>
          <Typography className={classes.title} variant='h4'>{mangaData.title}</Typography>
          {user?.admin && (
            <div className={classes.titleBarButtonsContainer}>
              <Link href={`/admin/manga/${mangaData.manga_id}`} prefetch={false}>
                <Tooltip title='Admin page'>
                  <IconButton>
                    <SettingsIcon />
                  </IconButton>
                </Tooltip>
              </Link>
              <Tooltip title='Edit chapters'>
                <IconButton onClick={startEditing}>
                  <EditIcon />
                </IconButton>
              </Tooltip>
            </div>
          )}
        </div>
        <div className={classes.details}>
          <a href={mangaData.mal} target='_blank' rel='noreferrer noopener'>
            <img
              src={mangaData.cover}
              className={classes.thumbnail}
              alt={mangaData.title}
            />
          </a>
          <Grid
            container
            justify='space-between'
            className={classes.rootGrid}
          >
            <Grid
              container
              direction='column'
              className={classes.infoGrid}
            >
              <MangaInfo mangaData={mangaData} />
              <MangaAliases aliases={mangaData.aliases} />
            </Grid>
            <MangaSourceList
              classesProp={[classes.sourceList]}
              items={mangaData.services}
              userFollows={userFollows}
              followUnfollow={(serviceId) => followUnfollow(mangaData.manga_id, serviceId)}
            />
          </Grid>
        </div>
        {isAuthenticated && (
          <Button
            variant='contained'
            color='primary'
            onClick={followUnfollow(mangaData.manga_id, null)}
            className={classes.followButton}
          >
            {userFollows.indexOf(null) < 0 ? 'Follow' : 'Unfollow'}
          </Button>
        )}

        <Tabs onChange={changeTab} value={activeTab}>
          <Tab label='Chapters' value={0} />
          <Tab label='Stats' value={1} />
        </Tabs>
        <TabPanelCustom value={activeTab} index={0} noRerenderOnChange>
          <ChapterList
            chapters={mangaChapters}
            editable={editing}
            serviceUrlFormats={serviceUrlFormats}
            mangaId={mangaData.manga_id}
          />
        </TabPanelCustom>
        <TabPanelCustom value={activeTab} index={1} noRerenderOnChange>
          <ReleaseHeatmap
            dataRows={releaseData}
          />
        </TabPanelCustom>
      </Paper>
    </Container>
  );
}

export default Manga;
