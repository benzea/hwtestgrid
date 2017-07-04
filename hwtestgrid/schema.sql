drop table if exists hwtestdb;
create table hwtestdb (
  machine TEXT,

  -- NOTE: The selection of what to cache here will need to change in the future
  'manufacturer' TEXT,
  'product' TEXT, 
  'os' TEXT,
  'time' DATETIME,

  'unique_identifier' TEXT UNIQUE,

  'bundle' TEXT,
  'cache' JSON
);


